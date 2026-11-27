import pytest
from fastapi.testclient import TestClient
from test_search import PAGES

from seekr import config, db
from seekr.index import bm25, embed, pagerank
from seekr.server import api


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    """A tiny index (the 3 pages from test_search), a normal key and an admin key, and a running app."""
    path = tmp_path_factory.mktemp("api") / "t.db"
    conn = db.connect(path)
    for doc_id, (url, (title, text)) in enumerate(PAGES.items(), start=1):
        conn.execute("INSERT INTO documents (id, url, title, language, word_count, published) "
                 "VALUES (?, ?, ?, 'en', ?, '')",
                     (doc_id, url, title, len(text.split())))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))
        db.save_page(conn, url, url, 200, title, "", list(PAGES))
    bm25.build_index(conn)
    embed.embed_chunks(conn)
    pagerank.compute_pagerank(conn)
    user, admin = api.create_key(conn, "tests"), api.create_key(conn, "admin", admin=True)
    with TestClient(api.create_app(path)) as client:
        yield client, {"Authorization": f"Bearer {user}"}, {"Authorization": f"Bearer {admin}"}, conn


def test_keys_are_required(setup):
    client, *_ = setup
    assert client.get("/api/v1/search?q=rust").status_code == 401
    assert client.get("/api/v1/search?q=rust", headers={"Authorization": "Bearer sk_wrong"}).status_code == 401


def test_only_the_hash_is_stored(setup):
    client, user, _, conn = setup
    raw_key = user["Authorization"].split()[1]
    stored = [row[0] for row in conn.execute("SELECT key_hash FROM api_keys")]
    assert raw_key not in stored and api.hash_key(raw_key) in stored


def test_search(setup):
    client, user, *_ = setup
    response = client.get("/api/v1/search", params={"q": "free memory without garbage collector"}, headers=user)
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["url"] == "https://x.com/rust-ownership"
    assert 0 <= body["results"][0]["relevance"] <= 1
    assert "pagerank" in body["results"][0]["signals"]
    assert "image" in body["results"][0]


def test_bad_parameters_are_rejected(setup):
    client, user, *_ = setup
    assert client.get("/api/v1/search?q=rust&limit=500", headers=user).status_code == 422
    assert client.get("/api/v1/search?q=", headers=user).status_code == 422


def test_page_and_stats(setup):
    client, user, *_ = setup
    page = client.get("/api/v1/page", params={"url": "https://x.com/cooking"}, headers=user).json()
    assert page["title"] == "Pasta recipes" and page["chunks"] == 1
    assert client.get("/api/v1/page", params={"url": "https://nope.com/"}, headers=user).status_code == 404
    assert client.get("/api/v1/stats", headers=user).json()["documents"] == 3


def test_seeds_need_an_admin_key(setup, tmp_path, monkeypatch):
    client, user, admin, _ = setup
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("https://a.com/\n")
    monkeypatch.setattr(config, "SEEDS_FILE", seeds)
    body = {"urls": ["https://a.com/", "https://B.com/docs/", "https://B.com/docs/"]}
    assert client.post("/api/v1/crawl/seeds", json=body, headers=user).status_code == 403
    assert client.post("/api/v1/crawl/seeds", json=body, headers=admin).json()["added"] == ["https://b.com/docs/"]
    assert seeds.read_text() == "https://a.com/\nhttps://b.com/docs/\n"
    assert client.post("/api/v1/crawl/seeds", json={"urls": ["ftp://x"]}, headers=admin).status_code == 422


def test_cors_header(setup):
    client, user, *_ = setup
    response = client.get("/api/v1/stats", headers={**user, "Origin": "https://myapp.example"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_rate_limiter_uses_a_sliding_window():
    limiter = api.RateLimiter(limit=2)
    assert limiter.allow("k", now=0) and limiter.allow("k", now=10)
    assert not limiter.allow("k", now=20)
    assert limiter.allow("other", now=20)  # every key has its own budget
    assert limiter.allow("k", now=61)  # the request at t=0 has left the window


def test_rate_limit_returns_429(setup):
    client, user, *_ = setup
    client.app.state.limiter = api.RateLimiter(limit=1)
    assert client.get("/api/v1/stats", headers=user).status_code == 200
    response = client.get("/api/v1/stats", headers=user)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_health_check_needs_no_key(setup):
    client, *_ = setup
    assert client.get("/healthz").json() == {"status": "ok"}
