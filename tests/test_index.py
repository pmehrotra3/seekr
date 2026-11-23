from seekr import db, index


def make_conn(tmp_path, pages):
    """pages: {title: text}. Each page becomes one document with one chunk."""
    conn = db.connect(tmp_path / "t.db")
    for doc_id, (title, text) in enumerate(pages.items(), start=1):
        conn.execute("INSERT INTO documents (id, url, title) VALUES (?, ?, ?)",
                     (doc_id, f"https://x.com/{doc_id}", title))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))
    index.build_index(conn)
    return conn


def test_query_is_escaped():
    assert index.to_fts_query('SQLite "FTS5"; DROP TABLE x--') == '"sqlite" OR "fts5" OR "drop" OR "table" OR "x"'
    assert index.to_fts_query("?!") == ""
    assert index.to_fts_query("how do I make a CDN") == '"cdn"'  # stopwords dropped
    assert index.to_fts_query("to be or") == '"to" OR "be" OR "or"'  # unless nothing else is left


def test_title_matches_rank_higher(tmp_path):
    conn = make_conn(tmp_path, {
        "Cooking pasta": "This page mentions sqlite once among many other words about food and sauce.",
        "SQLite full text search": "How to use the FTS5 extension.",
    })
    results = index.keyword_search(conn, "sqlite")
    assert [chunk_id for chunk_id, _ in results] == [2, 1]
    assert results[0][1] > results[1][1] > 0


def test_stemming_matches_word_forms(tmp_path):
    conn = make_conn(tmp_path, {"Postgres": "Creating indexes speeds up queries."})
    assert index.keyword_search(conn, "index query")[0][0] == 1


def test_build_index_is_incremental(tmp_path):
    conn = make_conn(tmp_path, {"A": "alpha"})
    assert index.build_index(conn) == 0
    conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (2, 1, 1, 'beta')")
    assert index.build_index(conn) == 1
    assert index.keyword_search(conn, "beta")[0][0] == 2


def test_no_words_no_results(tmp_path):
    assert index.keyword_search(make_conn(tmp_path, {"A": "alpha"}), "!!!") == []
