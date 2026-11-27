"""Videos from Dailymotion's public API (no key needed), stored as documents like crawled pages.

Only verified publishers (news outlets, labels, studios): Dailymotion's open uploads are mostly re-uploads.
"""
import html
import re
import time
from datetime import UTC, datetime

import httpx

from seekr import config
from seekr.index import extract

API = "https://api.dailymotion.com/videos"
FIELDS = "id,title,description,tags,thumbnail_720_url,created_time,owner.screenname,language"
CHANNELS = ("news", "music", "sport", "tech", "people", "tv", "school", "travel", "lifestyle", "animals", "auto",
            "videogames", "creation")
SPAM = re.compile(r"full (movie|drama|episode|series)|short drama|complete series|english sub|reelshort|dramabox", re.I)
TAGS = re.compile(r"<[^>]+>")


def read_topics(path=config.PACKAGE / "crawl" / "video_topics.txt"):
    return [line.strip() for line in open(path, encoding="utf-8") if line.strip() and not line.startswith("#")]


def to_document(video):
    description = html.unescape(TAGS.sub(" ", video.get("description") or "")).strip()
    language = video.get("language") or ""
    if language != "en" and video["title"].isascii():
        language = ""  # e.g. Hindi channels with English or Hinglish titles: still searchable by the English models
    text = " ".join(part for part in (video["title"], f"by {video['owner.screenname']}.", description,
                                      " ".join(video.get("tags") or [])) if part)
    return {
        "title": video["title"],
        "description": description[:300],
        "published": datetime.fromtimestamp(video["created_time"], UTC).isoformat(timespec="seconds"),
        "language": language,
        "text": text,
        "image": video.get("thumbnail_720_url") or "",
        "video": f"https://www.dailymotion.com/video/{video['id']}",
    }


def video_list(client, params, pages):
    """Up to `pages` pages of 100 videos (the API stops at 1,000 per list), one page at a time."""
    for page in range(1, pages + 1):
        try:
            response = client.get(API, params={**params, "fields": FIELDS, "verified": 1, "limit": 100, "page": page})
        except httpx.HTTPError:  # timeouts and dropped connections: skip the rest of this list
            return
        time.sleep(config.CRAWL_DELAY)
        if response.status_code != 200:  # the API fails on some lists now and then: skip that list
            return
        data = response.json()
        yield data["list"]
        if not data.get("has_more"):
            return


def import_videos(conn, topics=(), pages=10, transport=None):
    """Trending and newest videos per channel, plus the best matches per topic. Returns counts."""
    lists = [{"channel": channel, "sort": sort} for channel in CHANNELS for sort in ("trending", "recent")]
    lists += [{"search": topic, "sort": "relevance"} for topic in topics]
    counts = {"new": 0, "duplicate": 0, "known": 0, "spam": 0}
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, timeout=config.REQUEST_TIMEOUT, transport=transport) as client:
        for params in lists:
            for videos in video_list(client, params, pages):
                for video in videos:
                    url = f"https://www.dailymotion.com/video/{video['id']}"
                    if SPAM.search(video["title"]):
                        counts["spam"] += 1
                    elif conn.execute("SELECT 1 FROM documents WHERE url = ?", (url,)).fetchone():
                        counts["known"] += 1
                    else:
                        counts[extract.save_document(conn, url, to_document(video))] += 1
                conn.commit()  # before the next request: never hold the database while waiting on the network
    return counts
