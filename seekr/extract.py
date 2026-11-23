"""Turn raw HTML into clean text, split it into overlapping chunks, and store them."""
import hashlib
import json
import re
from concurrent.futures import ProcessPoolExecutor

import trafilatura

from seekr import config

HTML_LANG = re.compile(r"<html[^>]*\blang=[\"']?([a-zA-Z-]+)", re.IGNORECASE)


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
        conn.execute("INSERT INTO documents (url, word_count) VALUES (?, 0)", (url,))
        return "empty"
    digest = content_hash(doc["text"])
    original = conn.execute(
        "SELECT id FROM documents WHERE content_hash = ? AND duplicate_of IS NULL", (digest,)
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO documents (url, title, description, published, language, word_count, content_hash,"
        " duplicate_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (url, doc["title"], doc["description"], doc["published"], doc["language"],
         len(doc["text"].split()), digest, original["id"] if original else None),
    )
    if original:
        return "duplicate"
    chunks = [(cur.lastrowid, i, text) for i, text in enumerate(chunk_words(doc["text"]))]
    conn.executemany("INSERT INTO chunks (doc_id, position, text) VALUES (?, ?, ?)", chunks)
    return "new"


def extract_row(row):
    try:
        return extract(row[1], row[2], row[3])
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
