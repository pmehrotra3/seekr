import asyncio
import time

import httpx

from seekr import db
from seekr.crawl import crawler, discover

# Fake sites for the discovery checks: host -> {path: (status, body)}
SITES = {
    "good.org": {"/robots.txt": (404, ""), "/": (200, '<html lang="en"><title>Good</title>')},
    "closed.com": {"/robots.txt": (200, "User-agent: *\nDisallow: /"), "/": (200, "<html>")},
    "french.fr": {"/robots.txt": (404, ""), "/": (200, '<html lang="fr"><title>Bonjour</title>')},
}


def fake_web(request):
    status, body = SITES.get(request.url.host, {}).get(request.url.path, (404, ""))
    return httpx.Response(status, headers={"content-type": "text/html"}, text=body)


def add_page(conn, url, links):
    db.save_page(conn, url, url, 200, "", "", links)


def test_sites_linked_from_many_other_sites_score_higher(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    add_page(conn, "https://www.a.com/1", ["https://popular.org/", "https://a.com/2"])  # a.com -> a.com doesn't count
    add_page(conn, "https://a.com/3", ["https://popular.org/x"])  # the same site twice still counts once
    add_page(conn, "https://b.com/", ["https://popular.org/", "https://rare.org/"])
    assert discover.compute_sites(conn) == 2  # popular.org and rare.org
    sites = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT site, linked_from, score FROM sites")}
    assert sites["popular.org"] == (2, 1.0)
    assert sites["rare.org"][0] == 1 and 0 < sites["rare.org"][1] < 1
    assert "a.com" not in sites


def test_discover_checks_robots_and_language_and_remembers(tmp_path, monkeypatch):
    monkeypatch.setattr(discover.config, "DISCOVER_MIN_LINKS", 2)
    conn = db.connect(tmp_path / "t.db")
    for site in ("good.org", "closed.com", "french.fr", "facebook.com", "seed.com", "lonely.net"):
        conn.execute("INSERT INTO sites VALUES (?, ?, 0.5)", (site, 1 if site == "lonely.net" else 5))
    transport = httpx.MockTransport(fake_web)
    added = discover.discover(conn, ["https://www.seed.com/"], transport=transport)
    assert added == ["https://good.org/"]  # closed.com: robots; french.fr: language; facebook: skip list
    assert discover.found_seeds(conn) == ["https://good.org/"]
    assert discover.discover(conn, ["https://www.seed.com/"], transport=transport) == []  # nothing is checked twice


def test_crawl_stops_at_its_deadline(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    transport = httpx.MockTransport(fake_web)
    asyncio.run(crawler.crawl(["https://good.org/"], conn, transport=transport, until=time.monotonic()))
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
