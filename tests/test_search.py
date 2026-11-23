import numpy as np
import pytest

from seekr import db, embed, index, rank, search


def test_rrf_rewards_agreement():
    fused, ranks = search.rrf({"bm25": [("a", 9), ("b", 5)], "vector": [("b", 0.9), ("c", 0.8)]})
    assert max(fused, key=fused.get) == "b"  # 2nd + 1st beats a single 1st place
    assert ranks["b"] == {"bm25": 2, "vector": 1}
    assert np.isclose(fused["a"], 1 / 61)


def test_highlight_marks_words_and_escapes_html():
    snippet = search.highlight("Use <b>asyncio</b> to run Tasks concurrently.", "asyncio tasks")
    assert "&lt;b&gt;<mark>asyncio</mark>&lt;/b&gt;" in snippet
    assert "<mark>Tasks</mark>" in snippet


def test_freshness_fades_with_age():
    assert search.freshness("") == 0.5
    assert search.freshness("2000-01-01") < search.freshness("2020-01-01") < 1


def test_sigmoid_maps_logits_to_probabilities():
    assert np.isclose(search.sigmoid(0), 0.5)
    assert search.sigmoid(-10) < 0.001 < 0.999 < search.sigmoid(10)


PAGES = {
    "https://x.com/rust-ownership": ("Ownership in Rust", "Rust frees memory automatically when the owner of a value "
                                     "goes out of scope, so it needs no garbage collector. " * 3),
    "https://x.com/cooking": ("Pasta recipes", "Boil water, add salt and cook the pasta for nine minutes. " * 3),
    "https://x.com/de/rust": ("Eigentum in Rust", "Rust gibt Speicher frei, wenn der Besitzer den Gültigkeitsbereich "
                              "verlässt. " * 3),
}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    conn = db.connect(tmp_path_factory.mktemp("s") / "t.db")
    for doc_id, (url, (title, text)) in enumerate(PAGES.items(), start=1):
        language = "de" if "/de/" in url else "en"
        conn.execute("INSERT INTO documents (id, url, title, language, word_count, published) "
                     "VALUES (?, ?, ?, ?, ?, '')",
                     (doc_id, url, title, language, len(text.split())))
        conn.execute("INSERT INTO chunks (id, doc_id, position, text) VALUES (?, ?, 0, ?)", (doc_id, doc_id, text))
        db.save_page(conn, url, url, 200, title, "", list(PAGES))
    index.build_index(conn)
    embed.embed_chunks(conn)
    rank.compute_pagerank(conn)
    return search.SearchEngine(conn)


def test_full_search_ranks_the_relevant_page_first(engine):
    results = engine.search("how do I free memory without a garbage collector")
    assert results[0]["url"] == "https://x.com/rust-ownership"
    assert results[0]["relevance"] > 0.5 > results[-1]["relevance"]
    assert set(results[0]["signals"]) == {
        "bm25_rank", "vector_rank", "relevance", "pagerank", "freshness", "site_authority"}


def test_non_english_pages_are_skipped(engine):
    assert all("/de/" not in result["url"] for result in engine.search("rust speicher besitzer"))


def test_site_filter_and_modes(engine):
    assert engine.search("pasta", site="example.org") == []
    assert engine.search("pasta", mode="bm25")[0]["relevance"] is None
    assert engine.search("pasta", limit=1, offset=1)[0]["url"] != engine.search("pasta", limit=1)[0]["url"]


def test_snippet_starts_on_a_whole_word():
    words = [f"word{i}" for i in range(40)] + ["target"]
    snippet = search.highlight(" ".join(words), "target")
    assert snippet.startswith("…") and snippet[1:].split()[0] in words


def test_common_words_are_not_highlighted():
    snippet = search.highlight("How the event loop runs the tasks", "how does the event loop run")
    assert "<mark>event</mark>" in snippet and "<mark>the</mark>" not in snippet and "<mark>How</mark>" not in snippet
