import numpy as np

from seekr import evaluate


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
