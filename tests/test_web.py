import pytest
from fastapi.testclient import TestClient
from test_search import PAGES

from seekr import api, db, embed, index, rank, web


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("web") / "t.db"
    conn = db.connect(path)
    for doc_id, (url, (title, text)) in enumerate(PAGES.items(), start=1):
        conn.execute("INSERT INTO documents (id, url, title, language, word_count, published) "
                 "VALUES (?, ?, ?, 'en', ?, '')",
                     (doc_id, url, title, len(text.split())))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))
    index.build_index(conn)
    embed.embed_chunks(conn)
    rank.compute_pagerank(conn)
    with TestClient(web.create_site(path)) as client:
        yield client


def test_home_page_and_assets_are_served(client):
    home = client.get("/")
    assert home.status_code == 200 and 'class="wordmark"' in home.text
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
