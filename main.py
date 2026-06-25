import json as _json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config
import github_client
import markdown_cleaner
import vector_engine
from vector_engine import TIME_KEYWORDS
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


PERSONAL_KEYWORDS = [
    "experience", "work", "resume", "job", "education",
    "school", "cv", "hire", "background", "bachelor",
    "master", "degree", "career", "skill", "skills",
    "contact", "email",
]

GLOBAL_LIST_KEYWORDS = [
    "list all", "all my repo", "what repositories",
    "show all projects", "list of all", "what apps",
    "every repo", "all projects", "all your repos",
]


def is_personal_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in PERSONAL_KEYWORDS)


def is_global_list_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in GLOBAL_LIST_KEYWORDS)


def is_time_query(query: str) -> bool:
    return any(kw in query.lower() for kw in TIME_KEYWORDS)


def ingest_all_readmes():
    username = config.GITHUB_USERNAME
    logger.info("Starting ingestion for user '%s'", username)
    all_repos = github_client.get_repos(username)
    if not all_repos:
        logger.warning("No repos found for '%s'", username)
        return
    recent = [(name, date, desc, topics) for name, date, desc, topics in all_repos if _is_recent(date)]
    logger.info("Found %d repos updated in last 2 years (out of %d total)", len(recent), len(all_repos))

    active = {name for name, _, _, _ in recent}
    stored = db.get_all_repo_names()
    orphans = stored - active
    for name in orphans:
        db.delete_repo_chunks(name)
    if orphans:
        logger.info("Cleaned %d orphaned repos from ChromaDB", len(orphans))

    for repo_name, updated_at, description, topics in recent:
        readme = github_client.fetch_readme(username, repo_name)
        if readme is None:
            continue
        cleaned = markdown_cleaner.clean_markdown_for_rag(readme)
        if len(cleaned.strip()) < 30:
            placeholder_id = f"{repo_name}_empty_placeholder"
            placeholder_text = (
                f"This repository '{repo_name}' does not have a detailed README. "
                f"Description: {description or 'No description provided.'}"
            )
            extra = {"is_empty_placeholder": True}
            if repo_name == username:
                extra["is_bio"] = True
            chunks = [(placeholder_id, placeholder_text, extra)]
        else:
            chunks = vector_engine.chunk_text(cleaned, repo_name, updated_at=updated_at)
            if repo_name == username:
                for _, _, meta in chunks:
                    meta["is_bio"] = True
        db.upsert_documents(
            chunks,
            repo_name=repo_name,
            updated_at=updated_at,
            repo_description=description,
            repo_tags=topics,
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


app = FastAPI(title="ReadmeRag", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS.split(",") if config.CORS_ORIGINS != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")


def _route_query(query: str):
    if is_global_list_query(query):
        catalog = db.get_catalog()
        if not catalog:
            return None, None, []
        lines = [
            f"- **{r['repo_name']}** (updated {r['updated_at'][:10]}): {r['description']} [Tags: {r['tags']}]"
            for r in catalog
        ]
        context = "\n".join(lines)
        sources = [{"repo": r["repo_name"], "content_preview": r["description"][:200]} for r in catalog[:10]]
        return context, "catalog", sources
    elif is_personal_query(query):
        results = db.search(query, n_results=3, where={"is_bio": True})
        if not results:
            return None, None, []
        if results[0]["metadata"].get("is_empty_placeholder"):
            return (
                "I haven't added detailed experience/skill documentation yet. Stay tuned!",
                "guardrail",
                [],
            )
    else:
        results = db.search(query, n_results=3)
        if not results:
            return None, None, []
        if results[0]["metadata"].get("is_empty_placeholder"):
            repo = results[0]["metadata"]["repo_name"]
            return (
                f"I found the repository '{repo}', but the developer hasn't added a detailed README file for it yet.",
                "guardrail",
                [],
            )
    context = "\n\n---\n\n".join(r["content"] for r in results)
    sources = [
        {"repo": r["metadata"]["repo_name"], "content_preview": r["content"][:200]}
        for r in results
    ]
    return context, "readme", sources


@app.post("/api/chat")
@limiter.limit("5/minute")
async def chat_endpoint(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    history = body.get("history")
    if not query:
        return JSONResponse({"response": "Please provide a query."}, status_code=400)
    try:
        context, context_type, sources = _route_query(query)
        if context_type == "guardrail":
            return {"response": context, "sources": sources}
        if context is None:
            return {"response": "I couldn't find any relevant information to answer that.", "sources": []}
        answer = llm_client.chat(query, context, history=history, context_type=context_type or "readme")
        return {"response": answer, "sources": sources}
    except Exception as e:
        logger.error("Chat endpoint error: %s", e)
        return JSONResponse(
            {"response": "Sorry, an internal error occurred.", "sources": []},
            status_code=500,
        )


@app.post("/api/chat/stream")
@limiter.limit("5/minute")
async def chat_stream_endpoint(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    history = body.get("history")
    if not query:
        return JSONResponse({"response": "Please provide a query."}, status_code=400)

    context, context_type, sources = _route_query(query)

    async def generate():
        if context_type == "guardrail":
            yield f"data: {_json.dumps({'type': 'token', 'token': context})}\n\n"
            yield "data: [DONE]\n\n"
            return
        if context is None:
            yield f"data: {_json.dumps({'type': 'token', 'token': 'I could not find any relevant information.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        if sources:
            yield f"data: {_json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        try:
            for token in llm_client.chat_stream(query, context, history=history,
                                                  context_type=context_type or "readme"):
                yield f"data: {_json.dumps({'type': 'token', 'token': token})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e)
            yield f"data: {_json.dumps({'type': 'token', 'token': 'An error occurred while generating the response.'})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/ingest")
async def ingest_endpoint():
    ingest_all_readmes()
    return {"status": "ok", "total_chunks": db.count}


@app.get("/api/health")
@app.head("/api/health")
async def health():
    return {"status": "healthy", "chunks": db.count}
