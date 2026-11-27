"""`seekr export OUT.db`: a slim copy of the database with only what searching needs.

The crawl database keeps the raw HTML of every page (most of its size) and the crawl queue. A server needs
neither: it needs the searchable English pages, their chunks, keyword index, vectors, PageRank and site scores.
"""
from pathlib import Path

from seekr import db
from seekr.index import bm25, embed, pagerank

LOGO_PAGES = 20
KEEP = "d.word_count > 0 AND d.duplicate_of IS NULL AND (IFNULL(d.language, '') = '' OR d.language LIKE 'en%')"


def export(conn, out_path):
    """Write the slim database to out_path (which must not exist yet). Returns its row counts."""
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(f"{out_path} already exists")
    source = conn.execute("PRAGMA database_list").fetchone()[2]
    out = db.connect(out_path)
    out.execute(pagerank.SCHEMA)
    out.execute("ATTACH DATABASE ? AS src", (source,))
    out.execute(f"INSERT INTO documents SELECT d.* FROM src.documents d WHERE {KEEP}")
    out.execute("INSERT INTO chunks SELECT c.* FROM src.chunks c WHERE c.doc_id IN (SELECT id FROM documents)")
    out.execute("INSERT INTO embeddings SELECT e.* FROM src.embeddings e WHERE e.chunk_id IN (SELECT id FROM chunks)")
    out.execute("INSERT INTO pagerank SELECT p.* FROM src.pagerank p WHERE p.doc_id IN (SELECT id FROM documents)")
    out.execute("INSERT INTO sites SELECT * FROM src.sites")
    # An image or video on many pages is a site logo or promo, not about this page
    for column in ("image", "video"):
        out.execute(f"""UPDATE documents SET {column} = '' WHERE {column} IN (SELECT {column} FROM documents
                        WHERE {column} != '' GROUP BY {column} HAVING COUNT(*) > ?)""", (LOGO_PAGES,))
    out.commit()
    out.execute("DETACH DATABASE src")
    bm25.build_index(out)
    embed.load_vectors(out)  # writes the vector snapshot next to the new database
    counts = {table: out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("documents", "chunks", "embeddings", "pagerank", "sites")}
    out.execute("VACUUM")
    out.close()
    return counts
