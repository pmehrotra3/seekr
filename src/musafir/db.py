"""SQLite storage: one file on disk, a few small tables."""
import json
import sqlite3
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from musafir import config

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
    # Wait up to 10 minutes for another program's write instead of failing: crawl, index, archive and imports
    # run side by side, and on a busy machine one batch can take minutes. Reads never wait (WAL).
    conn = sqlite3.connect(path, timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")  # lets crawl, index and serve use the database at the same time
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    for column in ("image", "video"):  # databases made before Musafir kept images and videos
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


def pack_html(html):
    """Pages are stored compressed (about 6x smaller): raw HTML would fill the disk in days of crawling."""
    return zlib.compress(html.encode(), 6) if html else html


def unpack_html(value):
    """The HTML of a page row; older databases stored it uncompressed."""
    return zlib.decompress(value).decode() if isinstance(value, bytes) else value or ""


def save_page(conn, url, final_url, status, title, html, outlinks):
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)",
        (url, final_url, status, title, pack_html(html), json.dumps(outlinks), fetched_at),
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


ARCHIVE_SCHEMA = """CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, final_url TEXT, status INTEGER, title TEXT, html BLOB, fetched_at TEXT
);"""


def _packed(html):
    return html if isinstance(html, bytes) else pack_html(html)


def archive_pages(conn, dest, batch_size=2000):
    """Move the HTML of pages that are already indexed into the archive database `dest` (e.g. on a big, slow disk).

    HTML is over 90% of the crawl database, but once a page is indexed nothing reads it again. The page row stays,
    with its URL, links and fetch time: crawling, recrawling, PageRank and discovery need those. Returns pages moved.
    """
    archive = sqlite3.connect(dest, timeout=60)
    archive.execute("PRAGMA journal_mode=WAL")
    archive.executescript(ARCHIVE_SCHEMA)
    sql = """SELECT p.rowid, p.url, p.final_url, p.status, p.title, p.html, p.fetched_at FROM pages p
             JOIN documents d ON d.url = p.url WHERE p.rowid > ? AND p.html IS NOT NULL ORDER BY p.rowid LIMIT ?"""
    moved, last = 0, 0
    with ProcessPoolExecutor() as pool:  # compressing pages saved before Musafir compressed them is the slow part
        while rows := conn.execute(sql, (last, batch_size)).fetchall():
            last = rows[-1][0]
            htmls = pool.map(_packed, [row[5] for row in rows], chunksize=50)
            archive.executemany("INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?)",
                                [(*row[1:5], html, row[6]) for row, html in zip(rows, htmls, strict=True)])
            archive.commit()  # safely in the archive before it leaves the crawl database
            for attempt in range(10):  # the crawler may be writing too: wait for it rather than give up
                try:
                    conn.executemany("UPDATE pages SET html = NULL WHERE rowid = ?", [(row[0],) for row in rows])
                    conn.commit()
                    break
                except sqlite3.OperationalError:
                    if attempt == 9:
                        raise
                    conn.rollback()
            moved += len(rows)
            print(f"  moved {moved} pages...", flush=True)
    archive.close()
    return moved
