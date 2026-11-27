import numpy as np
import pytest

from seekr import db
from seekr.index import bm25, embed, pagerank
from seekr.search import ranker


def test_rrf_rewards_agreement():
    fused, ranks = ranker.rrf({"bm25": [("a", 9), ("b", 5)], "vector": [("b", 0.9), ("c", 0.8)]})
    assert max(fused, key=fused.get) == "b"  # 2nd + 1st beats a single 1st place
    assert ranks["b"] == {"bm25": 2, "vector": 1}
    assert np.isclose(fused["a"], 1 / 61)


def test_highlight_marks_words_and_escapes_html():
    snippet = ranker.highlight("Use <b>asyncio</b> to run Tasks concurrently.", "asyncio tasks")
    assert "&lt;b&gt;<mark>asyncio</mark>&lt;/b&gt;" in snippet
    assert "<mark>Tasks</mark>" in snippet


def test_freshness_fades_with_age():
    assert ranker.freshness("") == 0.5
    assert ranker.freshness("2000-01-01") < ranker.freshness("2020-01-01") < 1


def test_sigmoid_maps_logits_to_probabilities():
    assert np.isclose(ranker.sigmoid(0), 0.5)
    assert ranker.sigmoid(-10) < 0.001 < 0.999 < ranker.sigmoid(10)


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
    bm25.build_index(conn)
    embed.embed_chunks(conn)
    pagerank.compute_pagerank(conn)
    return ranker.SearchEngine(conn)


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
    snippet = ranker.highlight(" ".join(words), "target")
    assert snippet.startswith("…") and snippet[1:].split()[0] in words


def test_common_words_are_not_highlighted():
    snippet = ranker.highlight("How the event loop runs the tasks", "how does the event loop run")
    assert "<mark>event</mark>" in snippet and "<mark>the</mark>" not in snippet and "<mark>How</mark>" not in snippet


def test_pagerank_stage_breaks_ties_by_link_authority(engine):
    hybrid = engine.search("pasta", mode="hybrid")
    with_links = engine.search("pasta", mode="pagerank")
    assert {r["url"] for r in hybrid} == {r["url"] for r in with_links}  # same pages, maybe reordered
    assert with_links[0]["relevance"] is None  # no cross-encoder in this stage


def test_snippet_text_drops_tables_and_footnote_marks():
    text = "Adele | Born | 5 May 1988 | | Genres | Soul | Adele is a singer.[1] She sings.[edit]"
    assert ranker.clean_text(text) == "Adele Adele is a singer. She sings."


def test_main_title_and_summary():
    assert ranker.main_title("Adele - Wikipedia") == "Adele"
    assert ranker.main_title("Adele (given name) - Wikipedia") == "Adele (given name)"
    assert ranker.main_title("Yosemite (U.S. National Park Service)", keep_brackets=False) == "Yosemite"
    text = "Adele Appearance Adele Adkins is a singer. She was born in London. " + "More words here. " * 30
    assert ranker.summary(text, title="Adele") == ranker.summary("Adele Adkins is a singer. She was born in London. "
                                                                 + "More words here. " * 30)
    assert ranker.summary(text, title="Adele").startswith("Adele Adkins is a singer. She was born in London.")
    assert len(ranker.summary("word " * 200)) <= 320


def test_info_panel_only_for_the_page_about_the_query(engine):
    results = [{"title": "Pasta recipes", "url": "https://x.com/cooking", "image": None}]
    about = engine.about("pasta recipes", results)
    assert about["title"] == "Pasta recipes" and about["url"] == "https://x.com/cooking" and about["summary"]
    assert engine.about("something else", results) is None


def test_one_result_per_site_and_title():
    pages = [{"url": "https://billboard.com/a", "title": "Taylor Swift | Billboard"},
             {"url": "https://billboard.com/b", "title": "Taylor Swift | Billboard"},
             {"url": "https://wikipedia.org/t", "title": "Taylor Swift | Billboard"}]
    assert [page["url"] for page in ranker.one_per_title(pages)] == ["https://billboard.com/a", "https://wikipedia.org/t"]
