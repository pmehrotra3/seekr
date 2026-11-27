"""SQLite storage: one file on disk, a few small tables."""
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from seekr import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    url    TEXT PRIMARY KEY,
    host   TEXT NOT NULL,
    depth  INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'  -- queued, done, failed, error or blocked
);
CREATE INDEX IF NOT EXISTS frontier_next ON frontier (host, status, depth);

CREATE TABLE IF NOT EXISTS pages (
    url        TEXT PRIMARY KEY,
    final_url  TEXT,
    status     INTEGER,
    title      TEXT,
    html       TEXT,
    outlinks   TEXT,  -- JSON list of absolute URLs
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS pages_fetched ON pages (fetched_at);  -- the oldest pages are recrawled first

-- One row per crawled page. Duplicates and pages without main text get no chunks.
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY,
    url          TEXT UNIQUE NOT NULL,
    title        TEXT,
    description  TEXT,
    published    TEXT,
    language     TEXT,
    word_count   INTEGER,
    content_hash TEXT,
    duplicate_of INTEGER,
    image        TEXT, -- preview image (https URL), '' if none, NULL if not looked for yet
    video        TEXT  -- embedded video (YouTube/Vimeo/og:video URL), '' if none, NULL if not looked for yet
);
CREATE INDEX IF NOT EXISTS documents_hash ON documents (content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    doc_id   INTEGER NOT NULL,
    position INTEGER NOT NULL,
    text     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY,
    vector   BLOB NOT NULL  -- float32 bytes, length 1.0
);

CREATE TABLE IF NOT EXISTS sites (
    site        TEXT PRIMARY KEY,  -- host without "www."
    linked_from INTEGER NOT NULL,  -- how many other sites link to it
    score       REAL NOT NULL      -- 0..1 on a log scale
);

CREATE TABLE IF NOT EXISTS discovered (
    site        TEXT PRIMARY KEY,
    seed        TEXT,              -- the homepage we crawl, or NULL if the site failed our checks
    linked_from INTEGER NOT NULL,
    checked_at  TEXT NOT NULL
);
"""


def connect(path=None):
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)  # wait (up to 60 s) for another program's write instead of failing
    conn.execute("PRAGMA journal_mode=WAL")  # lets crawl, index and serve use the database at the same time
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    for column in ("image", "video"):  # databases made before Seekr kept images and videos
        if column not in columns:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT")
    return conn


def enqueue(conn, urls, depth):
    rows = [(url, url.split("/")[2], depth) for url in urls]
    conn.executemany("INSERT OR IGNORE INTO frontier (url, host, depth) VALUES (?, ?, ?)", rows)


def next_url(conn, host):
    return conn.execute(
        "SELECT url, depth FROM frontier WHERE host = ? AND status = 'queued' ORDER BY depth LIMIT 1",
        (host,),
    ).fetchone()


def mark(conn, url, status):
    conn.execute("UPDATE frontier SET status = ? WHERE url = ?", (status, url))


def redirect_targets(conn, urls):
    """Where these URLs ended up after redirects, for the ones that were redirected."""
    marks = ",".join("?" * len(urls))
    sql = f"SELECT final_url FROM pages WHERE url IN ({marks}) AND final_url != url"
    return [row["final_url"] for row in conn.execute(sql, urls)]


def requeue_errors(conn):
    conn.execute("UPDATE frontier SET status = 'queued' WHERE status = 'error'")


def count_done(conn, host):
    sql = "SELECT COUNT(*) FROM frontier WHERE host = ? AND status = 'done'"
    return conn.execute(sql, (host,)).fetchone()[0]


def save_page(conn, url, final_url, status, title, html, outlinks):
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (url, final_url, status, title, html, json.dumps(outlinks), fetched_at),
    )


def host_stats(conn):
    return conn.execute(
        """SELECT host,
                  SUM(status = 'done')    AS done,
                  SUM(status = 'queued')  AS queued,
                  SUM(status = 'failed')  AS failed,
                  SUM(status = 'error')   AS error,
                  SUM(status = 'blocked') AS blocked
           FROM frontier GROUP BY host ORDER BY host"""
    ).fetchall()


def forget_document(conn, url):
    """Drop a page's document (and copies of it) with its chunks, keyword index and vectors; `index` redoes it."""
    sql = "SELECT id FROM documents WHERE url = ? OR duplicate_of IN (SELECT id FROM documents WHERE url = ?)"
    ids = [row[0] for row in conn.execute(sql, (url, url))]
    for doc_id in ids:
        chunk_ids = [(row[0],) for row in conn.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))]
        conn.executemany("DELETE FROM embeddings WHERE chunk_id = ?", chunk_ids)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'chunks_fts'").fetchone():
            conn.executemany("DELETE FROM chunks_fts WHERE rowid = ?", chunk_ids)
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def forget_page(conn, url):
    """A page that is gone (404) or now off-limits: remove it from the index for good."""
    forget_document(conn, url)
    conn.execute("DELETE FROM pages WHERE url = ?", (url,))
    mark(conn, url, "failed")


def touch_page(conn, url):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("UPDATE pages SET fetched_at = ? WHERE url = ?", (now, url))
