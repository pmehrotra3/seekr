import pytest
from fastapi.testclient import TestClient
from test_search import PAGES

from seekr import db
from seekr.index import bm25, embed, pagerank
from seekr.server import api, web


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("web") / "t.db"
    conn = db.connect(path)
    for doc_id, (url, (title, text)) in enumerate(PAGES.items(), start=1):
        conn.execute("INSERT INTO documents (id, url, title, language, word_count, published) "
                 "VALUES (?, ?, ?, 'en', ?, '')",
                     (doc_id, url, title, len(text.split())))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))
    bm25.build_index(conn)
    embed.embed_chunks(conn)
    pagerank.compute_pagerank(conn)
    with TestClient(web.create_site(path)) as client:
        yield client


def test_home_page_and_assets_are_served(client):
    home = client.get("/")
    assert home.status_code == 200 and 'id="key-form"' in home.text
    assert client.get("/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/style.css").headers["content-type"].startswith("text/css")


def test_ui_search_needs_no_key(client):
    body = client.get("/ui/search", params={"q": "free memory without a garbage collector"}).json()
    assert body["results"][0]["url"] == "https://x.com/rust-ownership"


def test_api_still_needs_a_key(client):
    assert client.get("/api/v1/search?q=rust").status_code == 401


def test_ui_search_is_rate_limited_per_visitor(client):
    client.app.state.ui_limiter = api.RateLimiter(limit=1)
    assert client.get("/ui/search?q=pasta").status_code == 200
    assert client.get("/ui/search?q=pasta").status_code == 429


def test_anyone_can_get_a_free_api_key_that_works(client):
    client.app.state.signup_limiter = api.RateLimiter(limit=2, window=3600)
    key = client.post("/ui/keys", json={"name": "my weekend project"}).json()["key"]
    response = client.get("/api/v1/search?q=pasta", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    admin_only = client.post("/api/v1/crawl/seeds", json={"urls": []}, headers={"Authorization": f"Bearer {key}"})
    assert admin_only.status_code == 403  # never an admin key
    assert client.post("/ui/keys", json={}).status_code == 200
    assert client.post("/ui/keys", json={}).status_code == 429  # third key within the hour
    assert client.post("/ui/keys", json={"name": "x" * 81}).status_code == 422


def test_pages_are_never_served_stale_from_a_cache(client):
    for path in ("/", "/app.js", "/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_asset_urls_change_when_their_content_does(client):
    import re

    versions = re.findall(r'(?:app\.js|style\.css)\?v=([0-9a-f]{10})"', client.get("/").text)
    assert len(versions) == 2 and versions[0] == versions[1]


def test_tabs_and_their_validation(client):
    client.app.state.ui_limiter = api.RateLimiter(limit=100)  # other tests used up the per-minute budget
    for kind in ("all", "images", "videos", "news"):
        assert client.get(f"/ui/search?q=pasta&kind={kind}").status_code == 200
    assert client.get("/ui/search?q=pasta&kind=podcasts").status_code == 422


def test_keys_live_apart_from_the_index(tmp_path):
    keys = api.keys_db(tmp_path / "keys.db")
    key = api.create_key(keys, "survives index swaps")
    index = db.connect(tmp_path / "serve.db")
    assert "api_keys" not in {row[0] for row in index.execute("SELECT name FROM sqlite_master")}
    assert api.keys_db(tmp_path / "keys.db").execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] == 1 and key
