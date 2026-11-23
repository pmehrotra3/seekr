import asyncio

import httpx
import pytest

from seekr import config, crawler, db

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
