import sqlite3
import time

from seekr import __main__ as cli
from seekr import config, db
from seekr.index import embed, extract, pagerank
from seekr.search import ranker


def add_page(conn, doc_id, text):
    conn.execute("INSERT INTO documents (id, url, title, language, word_count, published) "
                 "VALUES (?, ?, ?, 'en', ?, '')",
                 (doc_id, f"https://x.com/{doc_id}", text, len(text.split())))
    conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))


def test_database_can_be_read_while_another_program_writes(tmp_path):
    writer, reader = db.connect(tmp_path / "t.db"), db.connect(tmp_path / "t.db")
    assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.enqueue(writer, ["https://a.com/"], depth=0)  # an open, uncommitted write
    assert reader.execute("SELECT COUNT(*) FROM frontier").fetchone()[0] == 0  # readers aren't blocked


def test_search_engine_picks_up_new_embeddings(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.execute(pagerank.SCHEMA)
    add_page(conn, 1, "Rust ownership rules")
    embed.embed_chunks(conn)
    engine = ranker.SearchEngine(conn)
    assert list(engine.vectors.chunk_ids) == [1]
    add_page(conn, 2, "Python asyncio event loop")
    embed.embed_chunks(conn)
    engine.refresh()
    assert list(engine.vectors.chunk_ids) == [1, 2]


def test_live_indexes_while_the_crawl_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "crawl_forever", lambda: time.sleep(0.5))  # a fake crawl that ends quickly
    monkeypatch.setattr(cli, "cmd_index", lambda args: calls.append("index"))
    monkeypatch.setattr(cli, "cmd_rank", lambda args: calls.append("rank"))
    monkeypatch.setattr(cli, "cmd_discover", lambda args: calls.append("discover"))
    monkeypatch.setattr(config, "LIVE_INTERVAL", 0.1)
    cli.main(["live"])
    assert calls[:3] == ["index", "rank", "discover"]  # right away, then again every LIVE_INTERVAL
    assert len(calls) >= 9


def test_one_broken_page_does_not_stop_indexing(monkeypatch):
    def broken(html, url, page_title=""):
        raise ValueError("Invalid \\escape")

    monkeypatch.setattr(extract, "extract", broken)
    assert extract.extract_row(("https://x.com/", "<html>", "https://x.com/", "")) is None


def test_search_reloads_at_most_every_refresh_seconds(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    conn.execute(pagerank.SCHEMA)
    add_page(conn, 1, "Rust ownership rules")
    embed.embed_chunks(conn)
    engine = ranker.SearchEngine(conn)
    add_page(conn, 2, "Python asyncio event loop")
    embed.embed_chunks(conn)
    engine.search("python", mode="vector")
    assert list(engine.vectors.chunk_ids) == [1]  # too soon: keep the loaded vectors, so the search stays fast
    monkeypatch.setattr(config, "REFRESH_SECONDS", 0)
    engine.search("python", mode="vector")
    assert list(engine.vectors.chunk_ids) == [1, 2]


def test_live_keeps_going_when_the_database_is_locked(monkeypatch):
    calls = []

    def locked(args):
        calls.append("index")
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cli, "crawl_forever", lambda: time.sleep(0.5))
    monkeypatch.setattr(cli, "cmd_index", locked)
    monkeypatch.setattr(config, "LIVE_INTERVAL", 0.1)
    cli.main(["live"])
    assert len(calls) >= 3  # it tried again every round instead of crashing
