"""Turn raw HTML into clean text, split it into overlapping chunks, and store them."""
import hashlib
import html as html_lib
import json
import re
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urljoin

import trafilatura

from musafir import config, db

HTML_LANG = re.compile(r"<html[^>]*\blang=[\"']?([a-zA-Z-]+)", re.IGNORECASE)
PREVIEW_TAG = re.compile(r"<meta[^>]+(?:property|name)=[\"'](?:og:image|twitter:image)(?::src)?[\"'][^>]*>", re.I)
CONTENT = re.compile(r"content=[\"']([^\"']+)", re.I)


VIDEO_TAG = re.compile(r"<meta[^>]+property=[\"']og:video(?::secure_url|:url)?[\"'][^>]*>", re.I)
IFRAME_SRC = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)", re.I)
YOUTUBE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")
VIMEO = re.compile(r"(?:player\.)?vimeo\.com/(?:video/)?(\d{6,})")


def page_video(html, url):
    """The video a page embeds (YouTube, Vimeo or its og:video), as a link people can open, or ''."""
    declared = [html_lib.unescape(found.group(1)) for tag in VIDEO_TAG.findall(html[:100_000])
                if (found := CONTENT.search(tag))]
    for src in declared + IFRAME_SRC.findall(html):
        if found := YOUTUBE.search(src):
            return f"https://www.youtube.com/watch?v={found.group(1)}"
        if found := VIMEO.search(src):
            return f"https://vimeo.com/{found.group(1)}"
    for src in declared:  # some other video file or player the page names
        src = urljoin(url, src.strip())
        if src.startswith("https://"):
            return src
    return ""


def page_image(html, url):
    """The preview image a page declares for link sharing (og:image), as an https URL, or ''."""
    for tag in PREVIEW_TAG.findall(html[:100_000]):  # it lives in <head>
        found = CONTENT.search(tag)
        src = urljoin(url, html_lib.unescape(found.group(1).strip())) if found else ""
        if src.startswith("https://"):  # http images would be blocked on an https site
            return src
    return ""


def extract(html, url, page_title=""):
    """Main text plus metadata, or None if the page has no real content (e.g. a pure link list)."""
    result = trafilatura.extract(html, url=url, output_format="json", with_metadata=True)
    if not result:
        return None
    data = json.loads(result)
    lang = HTML_LANG.search(html[:2000])
    return {
        "title": page_title or data.get("title") or url,
        "description": data.get("excerpt") or "",
        "published": data.get("date") or "",
        "language": lang.group(1).lower() if lang else "",
        "text": data["text"].replace("¶", ""),  # Sphinx docs add ¶ after every heading
        "image": page_image(html, url),
        "video": page_video(html, url),
    }


def chunk_words(text, size=config.CHUNK_WORDS, overlap=config.CHUNK_OVERLAP):
    """Split text into chunks of `size` words; neighbouring chunks share `overlap` words."""
    words = text.split()
    step = size - overlap
    return [" ".join(words[start : start + size]) for start in range(0, max(len(words) - overlap, 1), step)]


def content_hash(text):
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def save_document(conn, url, doc):
    """Insert one document and its chunks. Returns 'new', 'duplicate' or 'empty'."""
    if doc is None:
        conn.execute("INSERT INTO documents (url, word_count, image, video) VALUES (?, 0, '', '')", (url,))
        return "empty"
    digest = content_hash(doc["text"])
    original = conn.execute(
        "SELECT id FROM documents WHERE content_hash = ? AND duplicate_of IS NULL", (digest,)
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO documents (url, title, description, published, language, word_count, content_hash,"
        " duplicate_of, image, video) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (url, doc["title"], doc["description"], doc["published"], doc["language"],
         len(doc["text"].split()), digest, original["id"] if original else None, doc["image"],
         doc["video"]),
    )
    if original:
        return "duplicate"
    chunks = [(cur.lastrowid, i, text) for i, text in enumerate(chunk_words(doc["text"]))]
    conn.executemany("INSERT INTO chunks (doc_id, position, text) VALUES (?, ?, ?)", chunks)
    return "new"


def extract_row(row):
    try:
        return extract(db.unpack_html(row[1]), row[2], row[3])
    except Exception:  # e.g. trafilatura writing broken JSON for one odd page: skip that page, keep going
        return None


def index_pages(conn, batch_size=1000):
    """Extract every page that has no document yet, using all CPU cores. Returns counts."""
    sql = """SELECT p.url, p.html, p.final_url, p.title FROM pages p
             LEFT JOIN documents d ON d.url = p.url WHERE d.url IS NULL LIMIT ?"""
    counts = {"new": 0, "duplicate": 0, "empty": 0}
    with ProcessPoolExecutor() as pool:
        while rows := [tuple(row) for row in conn.execute(sql, (batch_size,))]:
            # One page per task, so a single huge page never leaves the other cores waiting.
            for row, doc in zip(rows, pool.map(extract_row, rows), strict=False):
                counts[save_document(conn, row[0], doc)] += 1
            conn.commit()
            print(f"  extracted {sum(counts.values())} pages...", flush=True)
    return counts


def add_media(conn, batch_size=2000):
    """Look up images and videos for documents indexed before Musafir kept them. Returns how many were checked."""
    sql = """SELECT d.id, p.html, p.final_url FROM documents d JOIN pages p ON p.url = d.url
             WHERE d.image IS NULL OR d.video IS NULL LIMIT ?"""
    total = 0
    while rows := conn.execute(sql, (batch_size,)).fetchall():
        pages = [(doc_id, db.unpack_html(html), url or "") for doc_id, html, url in rows]
        updates = [(page_image(html, url), page_video(html, url), doc_id) for doc_id, html, url in pages]
        conn.executemany("UPDATE documents SET image = ?, video = ? WHERE id = ?", updates)
        conn.commit()
        total += len(rows)
        print(f"  checked {total} pages for images and videos...", flush=True)
    return total
