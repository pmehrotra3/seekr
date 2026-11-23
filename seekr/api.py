"""REST API: search Seekr from any program, with API keys and a rate limit per key."""
import hashlib
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from seekr import config, db, embed, search
from seekr.urls import normalize_url

log = logging.getLogger(__name__)
KEYS_SCHEMA = """CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY, name TEXT NOT NULL, is_admin INTEGER NOT NULL, created_at TEXT NOT NULL);"""


def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(conn, name, admin=False):
    """Make a new random key and store only its hash. The key itself is shown once, then forgotten."""
    conn.executescript(KEYS_SCHEMA)
    key = "sk_" + secrets.token_urlsafe(24)
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("INSERT INTO api_keys VALUES (?, ?, ?, ?)", (hash_key(key), name, int(admin), created_at))
    conn.commit()
    return key


class RateLimiter:
    """Allows `limit` requests per key in any 60-second window (a "sliding window")."""

    def __init__(self, limit):
        self.limit, self.hits = limit, defaultdict(deque)

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        hits = self.hits[key]
        while hits and hits[0] <= now - 60:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class Signals(BaseModel):
    bm25_rank: int | None
    vector_rank: int | None
    relevance: float | None
    pagerank: float | None
    freshness: float | None
    site_authority: float | None


class Result(BaseModel):
    url: str
    title: str
    snippet: str  # HTML: page text is escaped, query words are wrapped in <mark>
    relevance: float | None
    final_score: float | None
    signals: Signals


class SearchResponse(BaseModel):
    query: str
    took_ms: int
    results: list[Result]


class Page(BaseModel):
    url: str
    title: str | None
    description: str | None
    published: str | None
    language: str | None
    word_count: int
    pagerank: float | None
    chunks: int


class Seeds(BaseModel):
    urls: list[str]


bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/v1")


async def api_key(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    """Every endpoint depends on this: a valid key that is under its rate limit.
    All handlers are `async` so they run on one thread: a SQLite connection may only be used by the thread
    that opened it."""
    if credentials is None:
        raise HTTPException(401, "Missing API key. Send the header: Authorization: Bearer <key>")
    key_hash = hash_key(credentials.credentials)
    row = request.app.state.conn.execute(
        "SELECT name, is_admin FROM api_keys WHERE key_hash = ?", (key_hash,)
    ).fetchone()
    if row is None:
        raise HTTPException(401, "Invalid API key")
    if not request.app.state.limiter.allow(key_hash):
        raise HTTPException(429, "Rate limit exceeded, try again in a minute", headers={"Retry-After": "60"})
    return row


async def admin_key(key=Depends(api_key)):
    if not key["is_admin"]:
        raise HTTPException(403, "This endpoint needs an admin key")
    return key


@router.get("/search", response_model=SearchResponse)
async def search_pages(
    request: Request,
    q: str = Query(min_length=1, max_length=200, description="What to search for"),
    limit: int = Query(10, ge=1, le=30),
    offset: int = Query(0, ge=0, le=29),
    site: str | None = Query(None, description="Only results from this host, e.g. docs.python.org"),
    key=Depends(api_key),
):
    started = time.perf_counter()
    results = request.app.state.engine.search(q, limit=limit, offset=offset, site=site)
    took_ms = round((time.perf_counter() - started) * 1000)
    log.info("search %r offset=%d site=%s -> %d results in %d ms", q, offset, site, len(results), took_ms)
    return {"query": q, "took_ms": took_ms, "results": results}


@router.get("/page", response_model=Page)
async def page_info(request: Request, url: str, key=Depends(api_key)):
    row = request.app.state.conn.execute(
        """SELECT d.url, d.title, d.description, d.published, d.language, d.word_count, r.score AS pagerank,
                  (SELECT COUNT(*) FROM chunks c WHERE c.doc_id = d.id) AS chunks
           FROM documents d LEFT JOIN pagerank r ON r.doc_id = d.id WHERE d.url = ? AND d.duplicate_of IS NULL""",
        (url,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "That URL is not in the index")
    return dict(row)


@router.get("/stats")
async def stats(request: Request, key=Depends(api_key)):
    count = lambda sql: request.app.state.conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "pages": count("SELECT COUNT(*) FROM pages"),
        "documents": count("SELECT COUNT(*) FROM documents WHERE duplicate_of IS NULL AND word_count > 0"),
        "chunks": count("SELECT COUNT(*) FROM chunks"),
        "embeddings": count("SELECT COUNT(*) FROM embeddings"),
        "device": embed.best_device(),
    }


@router.post("/crawl/seeds")
async def add_seeds(body: Seeds, key=Depends(admin_key)):
    """Add start URLs for the next crawl. Crawling itself runs from the command line."""
    urls = [normalize_url(url) for url in body.urls]
    if None in urls:
        raise HTTPException(422, "Every seed must be an http(s) URL")
    known = set(config.read_seeds())
    added = [url for url in dict.fromkeys(urls) if url not in known]
    with open(config.SEEDS_FILE, "a") as seeds_file:
        seeds_file.writelines(f"{url}\n" for url in added)
    return {"added": added, "next": "python -m seekr crawl && python -m seekr index && python -m seekr rank"}


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.conn = db.connect(db_path)
        app.state.conn.executescript(KEYS_SCHEMA)
        app.state.engine = search.SearchEngine(app.state.conn)  # loads vectors + models once, at startup
        app.state.engine.search("warm up")  # the GPU compiles its kernels on first use; do it before users arrive
        app.state.limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)
        yield
        app.state.conn.close()

    app = FastAPI(title="Seekr API", version="0.1", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        """For Docker and load balancers: the server only answers after the index and models are loaded."""
        return {"status": "ok"}

    return app
