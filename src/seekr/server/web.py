"""The search website: the files in static/, a key-less search endpoint and free API key signup."""
from fastapi import HTTPException, Query, Request
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

    static = StaticFiles(directory=config.PACKAGE / "server" / "static", html=True)
    app.mount("/", static, name="web")  # last: API routes win
    return app
