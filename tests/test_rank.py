import numpy as np

from seekr import db, rank


def test_cycle_gives_equal_scores():
    scores = rank.pagerank(3, [(0, 1), (1, 2), (2, 0)])
    assert np.allclose(scores, 1 / 3)


def test_most_linked_page_wins_and_scores_sum_to_one():
    scores = rank.pagerank(4, [(1, 0), (2, 0), (3, 0)])  # page 0 has no links of its own (dangling)
    assert scores.argmax() == 0
    assert np.isclose(scores.sum(), 1.0)
    assert np.allclose(scores[1:], scores[1])  # 1, 2 and 3 are in the same position


def test_known_values_for_a_small_graph():
    # Worked by hand: B and C link to A, A links to B. Solve r = 0.05 + 0.85 * (incoming shares).
    a, b, c = rank.pagerank(3, [(1, 0), (2, 0), (0, 1)])
    assert np.isclose(c, 0.05)
    assert np.isclose(a, 0.05 + 0.85 * (b + c))
    assert np.isclose(b, 0.05 + 0.85 * a)


def test_link_graph_follows_redirects_and_merges_duplicates(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.save_page(conn, "https://x.com/a", "https://x.com/a", 200, "A", "", ["https://x.com/old-b", "https://x.com/a"])
    db.save_page(conn, "https://x.com/old-b", "https://x.com/b", 200, "B", "", ["https://x.com/a-copy"])
    db.save_page(conn, "https://x.com/a-copy", "https://x.com/a-copy", 200, "A", "", [])
    conn.execute("INSERT INTO documents (id, url) VALUES (1, 'https://x.com/a'), (2, 'https://x.com/old-b')")
    conn.execute("INSERT INTO documents (id, url, duplicate_of) VALUES (3, 'https://x.com/a-copy', 1)")
    doc_ids, edges = rank.link_graph(conn)
    assert doc_ids == [1, 2]
    assert edges == [(0, 1), (1, 0)]  # a -> b (via redirect) and b -> a (via the duplicate); no self-link


def test_compute_pagerank_stores_scores(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.save_page(conn, "https://x.com/a", "https://x.com/a", 200, "A", "", ["https://x.com/b"])
    db.save_page(conn, "https://x.com/b", "https://x.com/b", 200, "B", "", [])
    conn.execute("INSERT INTO documents (id, url) VALUES (1, 'https://x.com/a'), (2, 'https://x.com/b')")
    assert rank.compute_pagerank(conn) == (2, 1)
    scores = dict(conn.execute("SELECT doc_id, score FROM pagerank").fetchall())
    assert scores[2] > scores[1]


def test_link_graph_survives_two_pages_ending_at_one_url(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.save_page(conn, "https://x.com/a", "https://x.com/a", 200, "A", "", ["https://x.com/b"])
    db.save_page(conn, "https://x.com/old-a", "https://x.com/a", 200, "A", "", [])  # also redirects to /a
    db.save_page(conn, "https://x.com/b", "https://x.com/b", 200, "B", "", [])
    conn.execute("INSERT INTO documents (id, url) VALUES (1, 'https://x.com/a'), (2, 'https://x.com/old-a'),"
                 " (3, 'https://x.com/b')")
    doc_ids, edges = rank.link_graph(conn)  # used to raise KeyError: 1
    assert doc_ids == [1, 2, 3]
