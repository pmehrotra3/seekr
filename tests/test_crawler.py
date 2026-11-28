import asyncio

import httpx
import pytest

from musafir import config, db
from musafir.crawl import crawler

# A tiny fake website. Each path maps to (status, content type, body).
SITE = {
    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private/\n"),
    "/": (200, "text/html", '<title>Home</title><a href="/a#x">A</a> <a href="/private/p">P</a>'
          ' <a href="https://other.com/">O</a> <a href="/file.pdf">PDF</a>'),
    "/a": (200, "text/html", '<title>Page A</title><a href="/?utm_source=x">home</a> <a href="/gone">G</a>'),
    "/gone": (404, "text/html", "not found"),
}


def fake_site(request):
    status, content_type, body = SITE.get(request.url.path, (404, "text/html", ""))
    return httpx.Response(status, headers={"content-type": content_type}, text=body)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CRAWL_DELAY", 0)
    return db.connect(tmp_path / "test.db")


def run_crawl(conn, handler=fake_site):
    asyncio.run(crawler.crawl(["https://example.com/"], conn, transport=httpx.MockTransport(handler)))
    return {row["url"]: row["status"] for row in conn.execute("SELECT url, status FROM frontier")}


def test_crawl_follows_links_and_respects_robots(conn):
    frontier = run_crawl(conn)
    assert frontier == {
        "https://example.com/": "done",
        "https://example.com/a": "done",
        "https://example.com/private/p": "blocked",
        "https://example.com/gone": "failed",
    }
    titles = [row["title"] for row in conn.execute("SELECT title FROM pages ORDER BY url")]
    assert titles == ["Home", "Page A"]


def test_no_write_is_left_open_while_waiting_for_a_site(conn):
    open_writes = []

    def site(request):  # other programs (index, archive) can only write while the crawler has nothing open
        open_writes.append(conn.in_transaction)
        return fake_site(request)

    run_crawl(conn, site)
    assert len(open_writes) >= 4 and not any(open_writes)


def test_crawl_stops_at_page_limit(conn, monkeypatch):
    monkeypatch.setattr(config, "MAX_PAGES_PER_DOMAIN", 1)
    assert list(run_crawl(conn).values()).count("done") == 1


def test_crawl_retries_server_errors(conn, monkeypatch):
    monkeypatch.setattr(config, "RETRIES", 1)
    calls = []

    def flaky(request):
        calls.append(request.url.path)
        if request.url.path == "/" and calls.count("/") == 1:
            return httpx.Response(503)
        return fake_site(request)

    assert run_crawl(conn, flaky)["https://example.com/"] == "done"
    assert calls.count("/") == 2


def test_parse_page_finds_title_and_links():
    title, links = crawler.parse_page('<title> Hi </title><a href="b">b</a><a href="b#2">b</a>', "https://x.com/a/")
    assert title == "Hi"
    assert links == ["https://x.com/a/b"]


def test_network_errors_are_retried_on_the_next_run(conn, monkeypatch):
    monkeypatch.setattr(config, "RETRIES", 0)

    def offline(request):  # robots.txt loads, then the network drops
        if request.url.path == "/robots.txt":
            return fake_site(request)
        raise httpx.ConnectError("no network")

    assert run_crawl(conn, offline)["https://example.com/"] == "error"
    assert run_crawl(conn)["https://example.com/"] == "done"


def test_redirected_seed_extends_the_scope(conn):
    def redirecting(request):
        if request.url.path == "/docs/stable/":
            return httpx.Response(301, headers={"location": "/docs/6.1/"})
        if request.url.path == "/docs/6.1/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<a href="intro/">i</a>')
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Intro</title>")

    transport = httpx.MockTransport(redirecting)
    asyncio.run(crawler.crawl(["https://example.com/docs/stable/"], conn, transport=transport))
    statuses = dict(conn.execute("SELECT url, status FROM frontier").fetchall())
    assert statuses["https://example.com/docs/6.1/intro/"] == "done"


def test_redirected_seed_scope_survives_a_restart(conn):
    conn.execute("INSERT INTO frontier VALUES ('https://example.com/docs/stable/', 'example.com', 0, 'done')")
    conn.execute("INSERT INTO frontier VALUES ('https://example.com/docs/6.1/x', 'example.com', 1, 'queued')")
    conn.execute("INSERT INTO pages (url, final_url) VALUES (?, ?)",
                 ("https://example.com/docs/stable/", "https://example.com/docs/6.1/"))
    page = '<a href="/docs/6.1/y">y</a>'
    site = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=page))
    asyncio.run(crawler.crawl(["https://example.com/docs/stable/"], conn, transport=site))
    statuses = dict(conn.execute("SELECT url, status FROM frontier").fetchall())
    assert statuses["https://example.com/docs/6.1/y"] == "done"


def test_parse_page_follows_iframes():
    _, links = crawler.parse_page('<noscript><iframe src="toc.html"></iframe></noscript>', "https://x.com/book/")
    assert links == ["https://x.com/book/toc.html"]


def test_unreachable_robots_skips_the_host_for_now(conn):
    def down(request):
        return httpx.Response(503)

    assert run_crawl(conn, down)["https://example.com/"] == "queued"


def test_hosts_with_unreachable_robots_are_logged_and_skipped(tmp_path, caplog):
    conn = db.connect(tmp_path / "t.db")
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    with caplog.at_level("WARNING", logger="musafir.crawl.crawler"):
        asyncio.run(crawler.crawl(["https://example.com/"], conn, transport=down))
    assert "example.com: robots.txt unreachable" in caplog.text


def test_only_the_page_title_counts_not_icon_titles():
    page = '<title>Yosemite (U.S. National Park Service)</title><svg><title>Lock</title></svg>'
    assert crawler.parse_page(page, "https://nps.gov/")[0] == "Yosemite (U.S. National Park Service)"


def test_a_daily_budget_caps_new_pages_across_all_hosts(conn):
    asyncio.run(crawler.crawl(["https://example.com/"], conn, transport=httpx.MockTransport(fake_site), budget=1))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1


def test_recrawl_refreshes_changed_pages_and_removes_gone_ones(conn):
    from musafir.index import bm25, embed, extract

    for url in ("https://example.com/a", "https://example.com/gone"):
        db.save_page(conn, url, url, 200, "Old", "<title>Old</title><p>" + "old words here " * 40 + "</p>", [])
        conn.execute("UPDATE pages SET fetched_at = '2000-01-01' WHERE url = ?", (url,))
    extract.index_pages(conn)
    bm25.build_index(conn)
    embed.embed_chunks(conn)
    counts = asyncio.run(crawler.recrawl(conn, 10, transport=httpx.MockTransport(fake_site)))
    assert counts == {"refreshed": 1, "removed": 1, "skipped": 0}
    assert [row[0] for row in conn.execute("SELECT url FROM pages")] == ["https://example.com/a"]
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0  # forgotten, so `index` redoes it
    assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
    assert conn.execute("SELECT title FROM pages").fetchone()[0] == "Page A"  # the new version
