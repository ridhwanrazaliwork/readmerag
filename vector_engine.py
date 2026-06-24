import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

import numpy as np
import chromadb
import chromadb.errors

import config
import llm_client

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    repo_name: str,
    updated_at: str | None = None,
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[tuple[str, str, dict]]:
    paragraphs = text.split("\n\n")
    raw_chunks = []
    buffer = ""

    for para in paragraphs:
        if not buffer:
            buffer = para
        elif len(buffer) + len(para) + 2 <= chunk_size:
            buffer += "\n\n" + para
        else:
            raw_chunks.append(buffer)
            overlap_start = max(0, len(buffer) - overlap)
            buffer = buffer[overlap_start:] + "\n\n" + para

    if buffer.strip():
        raw_chunks.append(buffer)

    meta_suffix = ""
    if updated_at:
        date_str = updated_at[:10]
        meta_suffix = f"\n\n[Metadata: Repository={repo_name}, Last Updated={date_str}]"

    result = []
    for idx, chunk in enumerate(raw_chunks):
        chunk_with_meta = chunk.strip() + meta_suffix
        chunk_id = _make_chunk_id(repo_name, chunk_with_meta, idx)
        result.append((chunk_id, chunk_with_meta, {}))
    return result


def _make_chunk_id(repo_name: str, text: str, index: int) -> str:
    prefix = hashlib.md5(text[:60].encode()).hexdigest()[:8]
    return f"{repo_name}_{index}_{prefix}"


TIME_KEYWORDS = [
    "latest", "newest", "most recent", "recently",
    "last updated", "new project", "recent project",
    "new repo", "newest repo", "latest repo",
    "last month", "current", "past year",
]


class VectorDB:

    def __init__(self):
        self.client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        try:
            self.collection = self.client.get_collection("readme_chunks")
        except chromadb.errors.NotFoundError:
            self.collection = self.client.create_collection(
                name="readme_chunks",
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def count(self) -> int:
        return self.collection.count()

    @property
    def _db_path(self) -> str:
        return os.path.join(config.CHROMA_DB_PATH, "chroma.sqlite3")

    def get_all_repo_names(self) -> set[str]:
        if self.count == 0:
            return set()
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        return {m["repo_name"] for m in metas if "repo_name" in m}

    def get_catalog(self) -> list[dict]:
        if self.count == 0:
            return []
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        unique: dict[str, dict] = {}
        for m in metas:
            name = m.get("repo_name", "")
            if name and name not in unique:
                unique[name] = {
                    "repo_name": name,
                    "description": m.get("repo_description", ""),
                    "tags": m.get("repo_tags", ""),
                    "updated_at": m.get("updated_at", ""),
                }
        return list(unique.values())

    def delete_repo_chunks(self, repo_name: str):
        ids = self.collection.get(where={"repo_name": repo_name})["ids"]
        if not ids:
            return
        self.collection.delete(ids=ids)
        logger.info("Deleted %d orphan chunks for repo '%s'", len(ids), repo_name)

    def upsert_documents(
        self,
        chunks: list[tuple[str, str, dict]],
        repo_name: str,
        updated_at: str | None = None,
        repo_description: str | None = None,
        repo_tags: list[str] | None = None,
    ):
        if not chunks:
            return
        ids = []
        documents = []
        metadatas = []
        if updated_at is None:
            updated_at = datetime.now(timezone.utc).isoformat()
        updated_at_ts = int(updated_at[:10].replace("-", ""))
        tags_str = ", ".join(repo_tags) if repo_tags else ""
        for chunk_id, text, extra_meta in chunks:
            ids.append(chunk_id)
            documents.append(text)
            metadatas.append({
                "repo_name": repo_name,
                "updated_at": updated_at,
                "updated_at_ts": updated_at_ts,
                "repo_description": repo_description or "",
                "repo_tags": tags_str,
                **extra_meta,
            })
        embeddings = llm_client.get_embeddings(documents)
        if embeddings and len(embeddings) == len(documents):
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            logger.info("Upserted %d chunks for repo '%s'", len(chunks), repo_name)
        else:
            logger.warning("Embedding failed for repo '%s', skipping upsert", repo_name)

    def _get_time_filter(self, query: str) -> dict | None:
        query_lower = query.lower()
        if any(kw in query_lower for kw in TIME_KEYWORDS):
            from datetime import datetime, timedelta
            cutoff = (datetime.utcnow() - timedelta(days=180)).strftime("%Y%m%d")
            return {"updated_at_ts": {"$gte": int(cutoff)}}
        return None

    def _dense_search(self, query_embedding: list[float], limit: int = 18, where: dict | None = None) -> list[dict]:
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": limit,
            "include": ["documents", "metadatas", "distances", "embeddings"],
        }
        if where:
            kwargs["where"] = where
        results = self.collection.query(**kwargs)
        if not results["ids"][0]:
            return []
        candidates = []
        for i in range(len(results["ids"][0])):
            candidates.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
                "embedding": np.array(results["embeddings"][0][i]),
            })
        return candidates

    def _sanitize_fts_query(self, query: str) -> str | None:
        words = re.findall(r"[-\w]+", query.lower())
        words = [w for w in words if len(w) >= 2]
        if not words:
            return None
        return " OR ".join(words)

    def _bm25_search(self, query: str, query_embedding: list[float], limit: int = 18) -> list[dict]:
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return []
        db_path = self._db_path
        if not os.path.isfile(db_path):
            return []
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """
                SELECT e.embedding_id
                FROM embedding_fulltext_search f
                JOIN embeddings e ON CAST(e.seq_id AS INTEGER) = f.rowid
                WHERE embedding_fulltext_search MATCH ?
                ORDER BY bm25(embedding_fulltext_search)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            conn.close()
        except sqlite3.OperationalError:
            return []

        bm25_ids = [r[0] for r in rows]
        if not bm25_ids:
            return []

        fetched = self.collection.get(
            ids=bm25_ids,
            include=["documents", "metadatas", "embeddings"],
        )
        if not fetched["ids"]:
            return []

        by_id = {}
        for i in range(len(fetched["ids"])):
            by_id[fetched["ids"][i]] = {
                "id": fetched["ids"][i],
                "content": fetched["documents"][i],
                "metadata": fetched["metadatas"][i],
                "embedding": np.array(fetched["embeddings"][i]),
            }

        qv = np.array(query_embedding)
        candidates = []
        for cid in bm25_ids:
            if cid not in by_id:
                continue
            doc = by_id[cid]
            sim = self._cosine_sim(qv, doc["embedding"])
            doc["distance"] = 1.0 - sim
            candidates.append(doc)
        return candidates

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    @staticmethod
    def _rrf_fuse(
        dense_ranked_ids: list[str],
        bm25_ranked_ids: list[str],
        k: int = 60,
    ) -> list[str]:
        scores: dict[str, float] = {}
        for rank, cid in enumerate(dense_ranked_ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        for rank, cid in enumerate(bm25_ranked_ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
        return sorted_ids[:k]

    def search(self, query: str, n_results: int = 3, where: dict | None = None) -> list[dict]:
        query_embedding = llm_client.get_embeddings([query])
        if not query_embedding:
            return []

        query_vec = query_embedding[0]

        if where is not None:
            dense_pool = self._dense_search(query_vec, limit=n_results * 6, where=where)
        else:
            time_filter = self._get_time_filter(query)
            dense_pool = self._dense_search(query_vec, limit=n_results * 6, where=time_filter)
            if time_filter and len(dense_pool) < n_results * 2:
                logger.info("Time filter limited candidates (%d); falling back to unfiltered", len(dense_pool))
                dense_pool = self._dense_search(query_vec, limit=n_results * 6)

        if not dense_pool:
            return []

        bm25_pool = self._bm25_search(query, query_vec, limit=n_results * 6)

        dense_ids = [c["id"] for c in dense_pool]
        bm25_ids = [c["id"] for c in bm25_pool]

        fused_ids = self._rrf_fuse(dense_ids, bm25_ids, k=60)

        by_id: dict[str, dict] = {}
        for c in dense_pool:
            by_id[c["id"]] = c
        for c in bm25_pool:
            if c["id"] not in by_id:
                by_id[c["id"]] = c

        candidates = [by_id[cid] for cid in fused_ids if cid in by_id]
        logger.info(
            "Hybrid: dense=%d bm25=%d fused=%d candidate=%d",
            len(dense_pool), len(bm25_pool), len(fused_ids), len(candidates),
        )

        return self._mmr_select(candidates, n_results, lambda_mult=0.5)

    def _mmr_select(
        self,
        candidates: list[dict],
        n_results: int,
        lambda_mult: float = 0.5,
    ) -> list[dict]:
        if not candidates:
            return []
        selected_indices: list[int] = []
        remaining = list(range(len(candidates)))

        query_sims = [1.0 - c["distance"] for c in candidates]

        while len(selected_indices) < min(n_results, len(candidates)):
            best_score = -float("inf")
            best_pos = -1
            for pos, i in enumerate(remaining):
                sim_to_query = query_sims[i]
                if selected_indices:
                    max_sim_to_sel = max(
                        float(np.dot(candidates[i]["embedding"], candidates[s]["embedding"]))
                        for s in selected_indices
                    )
                else:
                    max_sim_to_sel = 0.0
                mmr_score = lambda_mult * sim_to_query - (1.0 - lambda_mult) * max_sim_to_sel
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_pos = pos
            selected_indices.append(remaining.pop(best_pos))

        return [candidates[i] for i in selected_indices]
