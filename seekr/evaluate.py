"""Measure search quality on hand-labelled queries: MRR@10 and nDCG@10 for each way of searching."""
import json
import math
import time
from pathlib import Path

from seekr import config

QUERIES_FILE = config.ROOT / "evals" / "queries.jsonl"
# hybrid = BM25 + vectors fused with RRF; pagerank = hybrid + link authority; full = + cross-encoder + final score
MODES = ["bm25", "vector", "hybrid", "pagerank", "full"]


def reciprocal_rank(urls, relevant):
    """1/position of the first relevant result in the top 10, or 0 if there is none."""
    for position, url in enumerate(urls[:10], start=1):
        if url in relevant:
            return 1 / position
    return 0.0


def ndcg(urls, relevant):
    """Discounted gain of every relevant result (worth less further down), divided by the best possible."""
    gain = sum(1 / math.log2(position + 1) for position, url in enumerate(urls[:10], start=1) if url in relevant)
    ideal = sum(1 / math.log2(position + 1) for position in range(1, min(len(relevant), 10) + 1))
    return gain / ideal


def load_queries(path=QUERIES_FILE):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))]


def evaluate(engine, queries):
    """Returns {mode: (MRR@10, nDCG@10, p50 ms, p95 ms)}, averaged over all queries."""
    report = {}
    for mode in MODES:
        mrr = total_ndcg = 0.0
        times = []
        for item in queries:
            start = time.perf_counter()
            urls = [result["url"] for result in engine.search(item["query"], limit=10, mode=mode)]
            times.append((time.perf_counter() - start) * 1000)
            mrr += reciprocal_rank(urls, set(item["relevant"]))
            total_ndcg += ndcg(urls, set(item["relevant"]))
        report[mode] = (mrr / len(queries), total_ndcg / len(queries), percentile(times, 50), percentile(times, 95))
    return report
