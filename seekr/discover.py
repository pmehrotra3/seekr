"""Which sites matter (how many other sites link to them), and finding new sites to crawl."""
import asyncio
import json
import logging
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from seekr import config, crawler

log = logging.getLogger(__name__)
# Share buttons and link shorteners are linked from everywhere but have no articles for us.
SKIP_SITES = {
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com", "youtube.com", "youtu.be",
    "tiktok.com", "pinterest.com", "reddit.com", "whatsapp.com", "wa.me", "t.me", "threads.net", "bsky.app",
    "google.com", "goo.gl", "bit.ly", "t.co", "apple.com", "apps.apple.com", "play.google.com", "amazon.com",
    "docs.google.com", "drive.google.com", "groups.google.com", "maps.google.com", "gist.github.com",
    "web.archive.org", "vimeo.com", "news.ycombinator.com", "creativecommons.org",
}
HTML_LANG = re.compile(r'<html[^>]*\blang="?([a-zA-Z-]+)', re.I)


def site_of(url):
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def site_links(conn):
    """{site: set of the other crawled sites that link to it}, from every crawled page's links."""
    linked_from = defaultdict(set)
    for row in conn.execute("SELECT url, outlinks FROM pages"):
        source = site_of(row["url"])
        for link in json.loads(row["outlinks"] or "[]"):
            target = site_of(link)
            if target and target != source:
                linked_from[target].add(source)
    return linked_from


def compute_sites(conn):
    """Rebuild the sites table. A site linked from many different sites is probably important."""
    counts = {site: len(sources) for site, sources in site_links(conn).items()}
    top = math.log1p(max(counts.values(), default=1))
    conn.execute("DELETE FROM sites")
    conn.executemany("INSERT INTO sites VALUES (?, ?, ?)",
                     [(site, n, math.log1p(n) / top) for site, n in counts.items()])
    conn.commit()
    return len(counts)


def found_seeds(conn):
    return [row["seed"] for row in conn.execute("SELECT seed FROM discovered WHERE seed IS NOT NULL")]


async def check_site(client, site):
    """The homepage URL if robots.txt lets us in and it's an English HTML page, else None."""
    robots = await crawler.load_robots(client, site)
    if robots is None or not robots.can_fetch(config.USER_AGENT, f"https://{site}/"):
        return None
    status, final_url, html = await crawler.fetch(client, f"https://{site}/")
    lang = HTML_LANG.search(html[:5000]) if html else None
    if not html or (lang and not lang.group(1).lower().startswith("en")):
        return None
    return final_url


async def check_sites(sites, transport=None):
    headers = {"User-Agent": config.USER_AGENT}
    async with httpx.AsyncClient(headers=headers, timeout=config.REQUEST_TIMEOUT, follow_redirects=True,
                                 transport=transport) as client:
        return await asyncio.gather(*(check_site(client, site) for site in sites))


def discover(conn, seeds, limit=None, transport=None):
    """Check the most-linked sites we don't crawl yet; remember each answer. Returns the new seeds."""
    known = {site_of(seed) for seed in seeds} | {row[0] for row in conn.execute("SELECT site FROM discovered")}
    rows = conn.execute("SELECT site, linked_from FROM sites WHERE linked_from >= ? ORDER BY linked_from DESC",
                        (config.DISCOVER_MIN_LINKS,))
    picked = [(site, n) for site, n in rows if site not in known and site not in SKIP_SITES]
    picked = picked[: limit or config.DISCOVER_PER_ROUND]
    results = asyncio.run(check_sites([site for site, _ in picked], transport))
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany("INSERT INTO discovered VALUES (?, ?, ?, ?)",
                     [(site, seed, n, now) for (site, n), seed in zip(picked, results, strict=False)])
    conn.commit()
    added = [seed for seed in results if seed]
    log.info("discovered %d new sites (%d checked)", len(added), len(picked))
    return added
