import numpy as np

from seekr.search import evaluate


def test_reciprocal_rank():
    assert evaluate.reciprocal_rank(["a", "b", "c"], {"c"}) == 1 / 3
    assert evaluate.reciprocal_rank(["a", "b"], {"z"}) == 0


def test_ndcg_is_one_for_a_perfect_ranking_and_lower_otherwise():
    assert np.isclose(evaluate.ndcg(["r1", "r2", "x"], {"r1", "r2"}), 1.0)
    assert evaluate.ndcg(["x", "r1", "r2"], {"r1", "r2"}) < 1.0
    assert evaluate.ndcg(["x"], {"r1"}) == 0


def test_eval_file_is_valid():
    queries = evaluate.load_queries()
    assert len(queries) >= 20
    assert all(item["query"] and item["relevant"] for item in queries)


def test_percentile():
    assert evaluate.percentile([5, 1, 3, 2, 4], 50) == 3
    assert evaluate.percentile(list(range(1, 101)), 95) == 96


class FakeEngine:
    def search(self, query, limit, mode):
        return [{"url": "https://good"}] if mode == "full" else [{"url": "https://bad"}, {"url": "https://good"}]


def test_evaluate_reports_every_stage_with_latency():
    report = evaluate.evaluate(FakeEngine(), [{"query": "q", "relevant": ["https://good"]}])
    assert list(report) == evaluate.MODES
    assert report["full"][0] == 1.0 and report["bm25"][0] == 0.5
    assert all(p50 >= 0 and p95 >= p50 for _, _, p50, p95 in report.values())


def test_eval_queries_have_a_split():
    queries = evaluate.load_queries()
    assert len(queries) >= 50
    assert {item["split"] for item in queries} == {"dev", "test"}
