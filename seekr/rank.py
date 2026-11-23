"""Authority: PageRank over the links between crawled pages."""
import json

import numpy as np

SCHEMA = "CREATE TABLE IF NOT EXISTS pagerank (doc_id INTEGER PRIMARY KEY, score REAL NOT NULL);"
DAMPING = 0.85  # chance the "random surfer" follows a link instead of jumping to a random page


def link_graph(conn):
    """Return (doc_ids, edges): edges are (from, to) positions in doc_ids, one per linked pair of pages."""
    rows = conn.execute(
        """SELECT p.url, p.final_url, p.outlinks, IFNULL(d.duplicate_of, d.id) AS doc_id
           FROM pages p JOIN documents d ON d.url = p.url"""
    ).fetchall()
    doc_of = {}  # any URL we crawled (before or after redirects) -> its document; duplicates -> the original
    for row in rows:
        doc_of[row["url"]] = doc_of[row["final_url"]] = row["doc_id"]
    doc_ids = sorted({row["doc_id"] for row in rows})  # not doc_of.values(): two pages can redirect to one URL
    position = {doc_id: i for i, doc_id in enumerate(doc_ids)}
    edges = set()
    for row in rows:
        source = position[row["doc_id"]]
        for link in json.loads(row["outlinks"] or "[]"):
            if link in doc_of and position[doc_of[link]] != source:
                edges.add((source, position[doc_of[link]]))
    return doc_ids, sorted(edges)


def pagerank(n, edges, damping=DAMPING, tolerance=1e-10, max_iterations=100):
    """Power iteration. Returns one score per node; the scores add up to 1."""
    if n == 0:
        return np.zeros(0)
    edges = np.array(edges, dtype=np.int64).reshape(-1, 2)
    source, target = edges[:, 0], edges[:, 1]
    out_degree = np.bincount(source, minlength=n)
    rank = np.full(n, 1 / n)
    for _ in range(max_iterations):
        passed_on = np.bincount(target, weights=rank[source] / out_degree[source], minlength=n)
        dangling = rank[out_degree == 0].sum()  # pages with no links share their score with everyone
        new_rank = (1 - damping) / n + damping * (passed_on + dangling / n)
        if np.abs(new_rank - rank).sum() < tolerance:
            return new_rank
        rank = new_rank
    return rank


def compute_pagerank(conn):
    """Rebuild the pagerank table from scratch. Returns (number of pages, number of links)."""
    conn.executescript(SCHEMA)
    doc_ids, edges = link_graph(conn)
    scores = pagerank(len(doc_ids), edges)
    conn.execute("DELETE FROM pagerank")
    conn.executemany("INSERT INTO pagerank VALUES (?, ?)", zip(doc_ids, scores.tolist(), strict=False))
    conn.commit()
    return len(doc_ids), len(edges)
