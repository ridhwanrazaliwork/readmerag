import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config
import github_client
import markdown_cleaner
import vector_engine
import llm_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

db = vector_engine.VectorDB()

limiter = Limiter(key_func=get_remote_address)


def _is_recent(updated_at: str) -> bool:
    cutoff = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year - 2)
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return updated >= cutoff
    except (ValueError, AttributeError):
        return True


def ingest_all_readmes():
    username = config.GITHUB_USERNAME
    logger.info("Starting ingestion for user '%s'", username)
    all_repos = github_client.get_repos(username)
    if not all_repos:
        logger.warning("No repos found for '%s'", username)
        return
    recent = [(name, date) for name, date in all_repos if _is_recent(date)]
    logger.info("Found %d repos updated in last 2 years (out of %d total)", len(recent), len(all_repos))

    active = {name for name, _ in recent}
    stored = db.get_all_repo_names()
    orphans = stored - active
    for name in orphans:
        db.delete_repo_chunks(name)
    if orphans:
        logger.info("Cleaned %d orphaned repos from ChromaDB", len(orphans))

    for repo_name, updated_at in recent:
        readme = github_client.fetch_readme(username, repo_name)
        if readme is None:
            continue
        cleaned = markdown_cleaner.clean_markdown_for_rag(readme)
        chunks = vector_engine.chunk_text(cleaned, repo_name, updated_at=updated_at)
        db.upsert_documents(
            chunks,
            repo_name=repo_name,
            updated_at=updated_at,
        )
    logger.info("Ingestion complete. Total chunks: %d", db.count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    if db.count == 0:
        logger.info("ChromaDB is empty. Running initial ingestion.")
        ingest_all_readmes()
    logger.info("Startup complete. ChromaDB has %d chunks.", db.count)
    yield
    logger.info("Shutting down...")


app = FastAPI(title="ReadmeRiddle", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS.split(",") if config.CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
@limiter.limit("5/minute")
async def chat_endpoint(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return JSONResponse({"response": "Please provide a query."}, status_code=400)
    try:
        results = db.search(query, n_results=3)
        if not results:
            return {"response": "I couldn't find any relevant information to answer that.", "sources": []}
        context = "\n\n---\n\n".join(r["content"] for r in results)
        answer = llm_client.chat(query, context)
        sources = [
            {"repo": r["metadata"]["repo_name"], "content_preview": r["content"][:200]}
            for r in results
        ]
        return {"response": answer, "sources": sources}
    except Exception as e:
        logger.error("Chat endpoint error: %s", e)
        return JSONResponse(
            {"response": "Sorry, an internal error occurred.", "sources": []},
            status_code=500,
        )


@app.post("/api/ingest")
async def ingest_endpoint():
    ingest_all_readmes()
    return {"status": "ok", "total_chunks": db.count}


@app.get("/api/health")
async def health():
    return {"status": "healthy", "chunks": db.count}
