import numpy as np
import pytest

from seekr import db
from seekr.index import bm25, embed, export, pagerank


def make_crawl_db(path):
    conn = db.connect(path)
    conn.execute(pagerank.SCHEMA)
    docs = [  # id, url, language, word_count, duplicate_of
        (1, "https://a.com/en", "en", 100, None),
        (2, "https://a.com/fr", "fr", 100, None),
        (3, "https://a.com/copy", "en", 100, 1),
        (4, "https://a.com/empty", "en", 0, None),
        (5, "https://a.com/nolang", "", 100, None),
    ]
    for doc_id, url, language, words, duplicate in docs:
        conn.execute("INSERT INTO documents (id, url, title, language, word_count, duplicate_of) "
                     "VALUES (?, ?, 'T', ?, ?, ?)", (doc_id, url, language, words, duplicate))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, 'rust ownership')",
                     (doc_id, doc_id))
        conn.execute("INSERT INTO embeddings VALUES (?, ?)", (doc_id, (np.ones(4, np.float32) / 2).tobytes()))
        conn.execute("INSERT INTO pagerank VALUES (?, 0.2)", (doc_id,))
    conn.execute("INSERT INTO pages (url, html) VALUES ('https://a.com/en', '<html>big</html>')")
    conn.execute("INSERT INTO sites VALUES ('a.com', 3, 0.5)")
    conn.execute("UPDATE documents SET image = 'https://a.com/photo.jpg' WHERE id = 1")
    conn.commit()
    return conn


def test_export_keeps_only_searchable_english_pages(tmp_path):
    counts = export.export(make_crawl_db(tmp_path / "crawl.db"), tmp_path / "serve.db")
    assert counts == {"documents": 2, "chunks": 2, "embeddings": 2, "pagerank": 2, "sites": 1}
    out = db.connect(tmp_path / "serve.db")
    assert out.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0  # no raw HTML
    tables = {row[0] for row in out.execute("SELECT name FROM sqlite_master")}
    assert "chunks_fts_content" not in tables  # contentless keyword index: no second copy of the text
    assert [hit[0] for hit in bm25.keyword_search(out, "ownership")] in ([1, 5], [5, 1])
    assert list(embed.load_vectors(out)[0]) == [1, 5]
    assert (tmp_path / "serve.db.vectors.npy").exists()
    assert out.execute("SELECT image FROM documents WHERE id = 1").fetchone()[0] == "https://a.com/photo.jpg"


def test_export_drops_site_logos(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "LOGO_PAGES", 1)  # an image on 2+ pages counts as a logo
    conn = make_crawl_db(tmp_path / "crawl.db")
    conn.execute("UPDATE documents SET image = 'https://a.com/logo.png'")
    conn.commit()
    export.export(conn, tmp_path / "serve.db")
    images = {row[0] for row in db.connect(tmp_path / "serve.db").execute("SELECT image FROM documents")}
    assert images == {""}


def test_export_never_overwrites(tmp_path):
    (tmp_path / "serve.db").write_text("keep me")
    with pytest.raises(FileExistsError):
        export.export(make_crawl_db(tmp_path / "crawl.db"), tmp_path / "serve.db")


def test_pages_are_stored_compressed_and_read_back(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    html = "<html><body>" + "hello " * 1000 + "</body></html>"
    db.save_page(conn, "https://a.com/", "https://a.com/", 200, "A", html, [])
    stored = conn.execute("SELECT html FROM pages").fetchone()[0]
    assert isinstance(stored, bytes) and len(stored) < len(html) / 10
    assert db.unpack_html(stored) == html
    assert db.unpack_html("<old uncompressed page>") == "<old uncompressed page>" and db.unpack_html(None) == ""


def test_archive_moves_only_indexed_html(tmp_path):
    import sqlite3

    conn = db.connect(tmp_path / "c.db")
    db.save_page(conn, "https://a.com/done", "https://a.com/done", 200, "A", "<p>indexed</p>", ["https://a.com/x"])
    conn.execute("INSERT INTO pages (url, html) VALUES ('https://a.com/old', '<p>saved before compression</p>')")
    db.save_page(conn, "https://a.com/new", "https://a.com/new", 200, "N", "<p>not indexed yet</p>", [])
    conn.executemany("INSERT INTO documents (url, word_count) VALUES (?, 1)", [("https://a.com/done",), ("https://a.com/old",)])
    assert db.archive_pages(conn, tmp_path / "archive.db", batch_size=1) == 2
    left = dict(conn.execute("SELECT url, html IS NOT NULL FROM pages"))
    assert left == {"https://a.com/done": 0, "https://a.com/old": 0, "https://a.com/new": 1}  # rows stay, HTML goes
    assert conn.execute("SELECT outlinks FROM pages WHERE url = 'https://a.com/done'").fetchone()[0] == '["https://a.com/x"]'
    archived = dict(sqlite3.connect(tmp_path / "archive.db").execute("SELECT url, html FROM pages"))
    assert {url: db.unpack_html(html) for url, html in archived.items()} == {
        "https://a.com/done": "<p>indexed</p>", "https://a.com/old": "<p>saved before compression</p>"}
    assert db.archive_pages(conn, tmp_path / "archive.db") == 0  # nothing left to move
