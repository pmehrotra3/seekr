"""The search website: the files in web/ plus a key-less search endpoint for the browser."""
from fastapi import HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from seekr import config
from seekr.server import api


def create_site(db_path=None):
    """The API app plus the website. A browser can't keep a secret key, so the page calls
    /ui/search, which needs no key but is rate-limited per visitor (IP address) instead."""
    app = api.create_app(db_path)
    app.state.ui_limiter = api.RateLimiter(config.UI_RATE_LIMIT_PER_MINUTE)

    @app.get("/ui/search", response_model=api.SearchResponse, include_in_schema=False)
    async def ui_search(
        request: Request, q: str = Query(min_length=1, max_length=200), offset: int = Query(0, ge=0, le=29)
    ):
        if not request.app.state.ui_limiter.allow(request.client.host):
            raise HTTPException(429, "Too many searches. Wait a minute and try again.", headers={"Retry-After": "60"})
        return await api.search_pages(request, q=q, limit=10, offset=offset, site=None, key=None)

    static = StaticFiles(directory=config.PACKAGE / "server" / "static", html=True)
    app.mount("/", static, name="web")  # last: API routes win
    return app
