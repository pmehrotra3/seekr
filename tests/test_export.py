import numpy as np
import pytest

from seekr import db, embed, export, index, rank


def make_crawl_db(path):
    conn = db.connect(path)
    conn.execute(rank.SCHEMA)
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
    conn.commit()
    return conn


def test_export_keeps_only_searchable_english_pages(tmp_path):
    counts = export.export(make_crawl_db(tmp_path / "crawl.db"), tmp_path / "serve.db")
    assert counts == {"documents": 2, "chunks": 2, "embeddings": 2, "pagerank": 2, "sites": 1}
    out = db.connect(tmp_path / "serve.db")
    assert out.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0  # no raw HTML
    tables = {row[0] for row in out.execute("SELECT name FROM sqlite_master")}
    assert "chunks_fts_content" not in tables  # contentless keyword index: no second copy of the text
    assert [hit[0] for hit in index.keyword_search(out, "ownership")] in ([1, 5], [5, 1])
    assert list(embed.load_vectors(out)[0]) == [1, 5]
    assert (tmp_path / "serve.db.vectors.npy").exists()


def test_export_never_overwrites(tmp_path):
    (tmp_path / "serve.db").write_text("keep me")
    with pytest.raises(FileExistsError):
        export.export(make_crawl_db(tmp_path / "crawl.db"), tmp_path / "serve.db")
