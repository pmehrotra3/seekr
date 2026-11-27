"""The search website: the files in static/, a key-less search endpoint and free API key signup."""
import hashlib

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from seekr import config
from seekr.server import api


class KeyRequest(BaseModel):
    name: str = Field("", max_length=80)  # what the key is for; optional


def create_site(db_path=None):
    """The API app plus the website. A browser can't keep a secret key, so the page calls
    /ui/search, which needs no key but is rate-limited per visitor (IP address) instead."""
    app = api.create_app(db_path)
    app.state.ui_limiter = api.RateLimiter(config.UI_RATE_LIMIT_PER_MINUTE)
    app.state.signup_limiter = api.RateLimiter(config.KEY_SIGNUPS_PER_HOUR, window=3600)

    @app.get("/ui/search", response_model=api.SearchResponse, include_in_schema=False)
    async def ui_search(
        request: Request, q: str = Query(min_length=1, max_length=200), offset: int = Query(0, ge=0, le=29)
    ):
        if not request.app.state.ui_limiter.allow(request.client.host):
            raise HTTPException(429, "Too many searches. Wait a minute and try again.", headers={"Retry-After": "60"})
        return await api.search_pages(request, q=q, limit=10, offset=offset, site=None, key=None)

    @app.post("/ui/keys", include_in_schema=False)
    async def ui_create_key(request: Request, body: KeyRequest):
        """A free, normal (non-admin) API key for anyone, a few per visitor per hour."""
        if not request.app.state.signup_limiter.allow(request.client.host):
            raise HTTPException(429, "You've made several keys already. Try again in an hour.")
        name = body.name.strip() or "free key"
        return {"key": api.create_key(request.app.state.conn, name), "limit_per_minute": config.RATE_LIMIT_PER_MINUTE}

    @app.middleware("http")
    async def always_revalidate(request: Request, call_next):
        """Browsers and Cloudflare must check for a newer version, so an update never mixes old and new files."""
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # Caches (the browser's, Cloudflare's) may keep app.js and style.css for hours. Their URLs carry a fingerprint of
    # their content, so a new version always gets a new URL.
    files = config.PACKAGE / "server" / "static"
    version = hashlib.sha256((files / "app.js").read_bytes() + (files / "style.css").read_bytes()).hexdigest()[:10]
    home = (files / "index.html").read_text().replace("?v=VERSION", f"?v={version}")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home_page():
        return home

    static = StaticFiles(directory=config.PACKAGE / "server" / "static", html=True)
    app.mount("/", static, name="web")  # last: API routes win
    return app
