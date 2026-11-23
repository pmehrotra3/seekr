"""Keyword search: a SQLite FTS5 full-text index over chunks, ranked with BM25."""
import re

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    title, text,
    tokenize = 'porter unicode61'  -- lowercase, strip accents, and stem: "indexes" matches "index"
);
"""
# Words in almost every chunk: matching them costs seconds on a big index and says nothing about relevance
STOPWORDS = {"the", "and", "for", "how", "can", "what", "with", "does", "are", "you", "your", "from", "that", "this",
             "when", "why", "which", "into", "about", "same", "a", "an", "i", "to", "of", "in", "on", "is", "it",
             "do", "my", "me", "we", "so", "or", "be", "at", "by", "as", "if", "up", "should", "make", "get", "there"}
TITLE_WEIGHT, TEXT_WEIGHT = 5.0, 1.0  # a word in the title counts 5x more than in the body


def build_index(conn):
    """Add every chunk that isn't indexed yet. Chunk ids only grow, so "new" means id > the last one."""
    conn.executescript(FTS_SCHEMA)
    last_id = conn.execute("SELECT IFNULL(MAX(rowid), 0) FROM chunks_fts").fetchone()[0]
    cur = conn.execute(
        """INSERT INTO chunks_fts (rowid, title, text)
           SELECT c.id, d.title, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
           WHERE c.id > ? ORDER BY c.id""",
        (last_id,),
    )
    conn.commit()
    return cur.rowcount


def to_fts_query(query):
    """Turn free text into a safe FTS5 query: every word quoted, joined with OR. Stopwords are dropped,
    unless the query has nothing else ("the who")."""
    words = list(dict.fromkeys(re.findall(r"\w+", query.lower())))
    words = [word for word in words if word not in STOPWORDS] or words
    return " OR ".join(f'"{word}"' for word in words)


def keyword_search(conn, query, limit=100):
    """Return [(chunk_id, bm25 score)], best first. Higher score = better match."""
    fts_query = to_fts_query(query)
    if not fts_query:
        return []
    rows = conn.execute(
        """SELECT rowid, bm25(chunks_fts, ?, ?) AS score FROM chunks_fts
           WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""",
        (TITLE_WEIGHT, TEXT_WEIGHT, fts_query, limit),
    )
    return [(row["rowid"], -row["score"]) for row in rows]  # SQLite's bm25() is negative: lower = better
