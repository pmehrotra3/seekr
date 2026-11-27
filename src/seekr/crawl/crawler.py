"""A small, polite, resumable web crawler."""
import asyncio
import logging
import time
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser

import httpx

from seekr import config, db
from seekr.crawl.urls import build_scopes, in_scope, normalize_url

RETRY_STATUSES = {None, 429, 500, 502, 503, 504}
log = logging.getLogger(__name__)


class LinkParser(HTMLParser):
    """Collects the page's <title> text, every <a href> and every <iframe src> on a page."""

    def __init__(self):
        super().__init__()
        self.title, self.links, self.in_title, self.titles_seen = "", [], False, 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "iframe" and attrs.get("src"):  # some docs load their table of contents this way
            self.links.append(attrs["src"])
        elif tag == "title":
            self.titles_seen += 1
            self.in_title = self.titles_seen == 1  # later <title>s label icons (SVG), e.g. "Lock"

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def parse_page(html, base_url):
    parser = LinkParser()
    parser.feed(html)
    links = {normalize_url(href, base_url) for href in parser.links}
    return parser.title.strip(), sorted(link for link in links if link)


async def load_robots(client, host):
    """Missing robots.txt (4xx) means allow all. Unreachable (5xx, network error) returns None."""
    try:
        resp = await client.get(f"https://{host}/robots.txt")
    except httpx.HTTPError:
        return None
    if resp.status_code >= 500:
        return None
    robots = RobotFileParser()
    if resp.status_code >= 400:
        robots.allow_all = True
    else:
        robots.parse(resp.text.splitlines())
    return robots


async def fetch_once(client, url):
    """Return (status, final_url, html). html is None for non-HTML or oversized pages."""
    async with client.stream("GET", url) as resp:
        final_url = str(resp.url)
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
            return resp.status_code, final_url, None
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if len(body) > config.MAX_PAGE_BYTES:
                return resp.status_code, final_url, None
        return resp.status_code, final_url, body.decode(resp.charset_encoding or "utf-8", "replace")


async def fetch(client, url):
    """fetch_once, retried with exponential backoff (1s, 2s, ...) on network errors, 429 and 5xx."""
    for attempt in range(config.RETRIES + 1):
        try:
            status, final_url, html = await fetch_once(client, url)
        except httpx.HTTPError:
            status, final_url, html = None, url, None
        if status not in RETRY_STATUSES or attempt == config.RETRIES:
            return status, final_url, html
        await asyncio.sleep(2**attempt)


async def crawl_host(client, conn, host, scopes, until=None):
    """Crawl one host, one request at a time, waiting between requests (and stopping at `until`)."""
    robots = await load_robots(client, host)
    if robots is None:  # can't read the rules, so stay away from this host until the next run
        log.warning("%s: robots.txt unreachable, skipping this host until the next run", host)
        return
    delay = max(config.CRAWL_DELAY, robots.crawl_delay(config.USER_AGENT) or 0)
    while db.count_done(conn, host) < config.MAX_PAGES_PER_DOMAIN and (until is None or time.monotonic() < until):
        row = db.next_url(conn, host)
        if row is None:
            break
        url, depth = row["url"], row["depth"]
        if not robots.can_fetch(config.USER_AGENT, url):
            db.mark(conn, url, "blocked")
            continue
        status, final_url, html = await fetch(client, url)
        log.debug("%s %s", status, url)
        if depth == 0 and final_url != url:  # a seed redirected, e.g. /en/stable/ -> /en/6.1/
            scopes.extend(build_scopes([final_url]))
        if html:
            title, links = parse_page(html, final_url)
            db.save_page(conn, url, final_url, status, title, html, links)
            if depth < config.MAX_DEPTH:
                db.enqueue(conn, [link for link in links if in_scope(link, scopes)], depth + 1)
        if html:
            db.mark(conn, url, "done")
        else:  # no status means a network error: worth retrying on the next run
            db.mark(conn, url, "failed" if status else "error")
            log.info("%s %s", status or "network error", url)
        conn.commit()
        await asyncio.sleep(delay)
    log.info("%s: done (%d pages)", host, db.count_done(conn, host))


async def crawl(seeds, conn, transport=None, until=None):
    """Crawl all seed hosts at the same time (each host politely, one request at a time)."""
    seed_urls = [normalize_url(seed) for seed in seeds]
    scopes = build_scopes(seed_urls + db.redirect_targets(conn, seed_urls))
    db.enqueue(conn, seed_urls, depth=0)
    db.requeue_errors(conn)
    conn.commit()
    hosts = sorted({host for host, _ in scopes})
    headers = {"User-Agent": config.USER_AGENT}
    async with httpx.AsyncClient(
        headers=headers, timeout=config.REQUEST_TIMEOUT, follow_redirects=True, transport=transport
    ) as client:
        await asyncio.gather(*(crawl_host(client, conn, host, scopes, until) for host in hosts))
