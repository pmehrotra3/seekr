"""Hybrid search: keyword + semantic candidates, then a cross-encoder decides how relevant each page is."""
import html
import math
import re
import time
from datetime import date
from urllib.parse import urlsplit

import numpy as np
import torch
from sentence_transformers import CrossEncoder

from seekr import config, discover, embed, index

CHUNK_SQL = """SELECT c.doc_id, c.text, d.url, d.title, d.published, d.language, d.word_count
               FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id = ?"""
STOPWORDS = index.STOPWORDS
_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        device = embed.best_device()
        _reranker = CrossEncoder(config.RERANK_MODEL, device=device, max_length=config.RERANK_MAX_TOKENS)
        if device != "cpu":
            _reranker.model.half()
    return _reranker


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def rrf(rankings, k=60):
    """Reciprocal Rank Fusion. rankings: {name: [(id, score), ...] best first} -> (fused scores, ranks)."""
    fused, ranks = {}, {}
    for name, hits in rankings.items():
        for rank, (item, _) in enumerate(hits, start=1):
            fused[item] = fused.get(item, 0.0) + 1 / (k + rank)
            ranks.setdefault(item, {})[name] = rank
    return fused, ranks


def query_words(query):
    return re.findall(r"\w+", query.lower())


def highlight(text, query, width=300):
    """A window of text around the first query word, HTML-escaped, with query words wrapped in <mark>."""
    words = [re.escape(word) for word in query_words(query) if len(word) > 2 and word not in STOPWORDS]
    pattern = re.compile(r"\b(?:" + "|".join(words) + r")\w*", re.IGNORECASE) if words else None
    first = pattern.search(text) if pattern else None
    start = max(0, first.start() - 80) if first else 0
    start = text.find(" ", start) + 1 if start else 0  # begin on a whole word
    window = ("…" if start else "") + text[start : start + width] + ("…" if start + width < len(text) else "")
    parts, last = [], 0
    for match in pattern.finditer(window) if pattern else []:
        parts += [html.escape(window[last : match.start()]), "<mark>", html.escape(match.group()), "</mark>"]
        last = match.end()
    return "".join(parts) + html.escape(window[last:])


def freshness(published):
    """1.0 for a page from today, 0.5 after a year, 0.33 after two... and 0.5 when there is no date."""
    try:
        age_years = (date.today() - date.fromisoformat(published[:10])).days / 365
    except (TypeError, ValueError):
        return 0.5
    return 1 / (1 + max(age_years, 0))


class SearchEngine:
    def __init__(self, conn):
        self.conn = conn
        self.version = None
        self.refresh()

    def refresh(self):
        """Reload the vectors and PageRank if `index` or `rank` changed them since the last load."""
        self.refreshed_at = time.monotonic()
        version = tuple(self.conn.execute(
            "SELECT (SELECT MAX(chunk_id) FROM embeddings), (SELECT COUNT(*) FROM pagerank), "
            "(SELECT COUNT(*) FROM sites)").fetchone())
        if version == self.version:
            return
        self.version = version
        self.vectors = embed.VectorIndex(self.conn)
        logs = {doc: math.log(score) for doc, score in self.conn.execute("SELECT doc_id, score FROM pagerank")}
        low, high = min(logs.values(), default=0.0), max(logs.values(), default=1.0)
        self.pagerank = {doc: (value - low) / ((high - low) or 1) for doc, value in logs.items()}  # 0..1
        self.sites = dict(self.conn.execute("SELECT site, score FROM sites").fetchall())

    def candidates(self, query, mode="full", site=None):
        """Best chunk per page from BM25 and/or vectors, fused with RRF. English pages only."""
        rankings = {}
        if mode in ("bm25", "hybrid", "pagerank", "full"):
            rankings["bm25"] = index.keyword_search(self.conn, query, config.CANDIDATES)
        if mode in ("vector", "hybrid", "pagerank", "full"):
            rankings["vector"] = self.vectors.search(embed.embed_query(query), config.CANDIDATES)
        fused, ranks = rrf(rankings)
        pages, seen = [], set()
        for chunk_id in sorted(fused, key=fused.get, reverse=True):
            page = dict(self.conn.execute(CHUNK_SQL, (chunk_id,)).fetchone())
            host = urlsplit(page["url"]).netloc
            if page["doc_id"] in seen or not (page["language"] or "en").startswith("en"):
                continue
            if site and host != site and not host.endswith("." + site):
                continue
            seen.add(page["doc_id"])
            pages.append({**page, "ranks": ranks[chunk_id], "rrf": fused[chunk_id]})
        return pages

    def rerank(self, query, pages):
        """Score each page: mostly the cross-encoder's relevance, plus authority, freshness and exact matches."""
        if not pages:
            return []
        pairs = [(query, f"{page['title']}\n{page['text']}") for page in pages]
        logits = get_reranker().predict(pairs, batch_size=16, activation_fn=torch.nn.Identity())
        words = query_words(query)
        best_rrf = max(page["rrf"] for page in pages)
        for page, logit in zip(pages, logits, strict=False):
            title_and_url = f"{page['title']} {page['url']}".lower()
            page["relevance"] = float(sigmoid(logit))
            page["pagerank"] = self.pagerank.get(page["doc_id"], 0.0)
            page["freshness"] = freshness(page["published"])
            page["exact"] = sum(word in title_and_url for word in words) / max(len(words), 1)
            page["site_authority"] = self.sites.get(discover.site_of(page["url"]), 0.0)
            page["final_score"] = (
                config.W_RELEVANCE * page["relevance"] + config.W_PAGERANK * page["pagerank"]
                + config.W_FRESHNESS * page["freshness"] + config.W_EXACT * page["exact"]
                + config.W_SITE * page["site_authority"]
                + config.W_RETRIEVAL * page["rrf"] / best_rrf  # how strongly BM25 + vectors agreed (0..1)
            )
            if page["word_count"] < config.THIN_PAGE_WORDS:
                page["final_score"] *= config.THIN_PAGE_PENALTY
        return sorted(pages, key=lambda page: page["final_score"], reverse=True)

    def search(self, query, limit=10, offset=0, site=None, mode="full"):
        if time.monotonic() - self.refreshed_at > config.REFRESH_SECONDS:  # reloading takes seconds on a big index
            self.refresh()
        pages = self.candidates(query, mode, site)
        if mode == "pagerank":  # hybrid + link authority, no cross-encoder: shows what PageRank adds on its own
            pages.sort(key=lambda page: page["rrf"] + config.W_RRF_PAGERANK * self.pagerank.get(page["doc_id"], 0.0),
                       reverse=True)
        if mode == "full":
            pages = self.rerank(query, pages[: config.RERANK_TOP])
        return [self.to_result(page, query) for page in pages[offset : offset + limit]]

    def to_result(self, page, query):
        return {
            "url": page["url"],
            "title": page["title"] or page["url"],
            "snippet": highlight(page["text"], query),
            "relevance": page.get("relevance"),
            "final_score": page.get("final_score"),
            "signals": {
                "bm25_rank": page["ranks"].get("bm25"),
                "vector_rank": page["ranks"].get("vector"),
                "relevance": page.get("relevance"),
                "pagerank": page.get("pagerank"),
                "freshness": page.get("freshness"),
                "site_authority": page.get("site_authority"),
            },
        }
