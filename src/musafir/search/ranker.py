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

from musafir import config
from musafir.crawl import discover
from musafir.index import bm25, embed

CHUNK_SQL = """SELECT c.doc_id, c.text, d.url, d.title, d.published, d.language, d.word_count, d.image, d.video
               FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id = ?"""
STOPWORDS = bm25.STOPWORDS
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


TABLE = re.compile(r"(?:\|[^|]{0,80}){2,}\|")  # table rows flattened to text: "| Born | 5 May 1988 |"
MARKERS = re.compile(r"\[(?:edit|\d{1,3}|[a-z])\]")  # Wikipedia's [edit] links and footnote marks like [1] or [a]
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def clean_text(text):
    """Page text without table markup and footnote marks, for snippets and summaries."""
    return " ".join(MARKERS.sub("", TABLE.sub(" ", text)).split())


def main_title(title, keep_brackets=True):
    """What a title names: 'Adele - Wikipedia' -> 'Adele'. Without brackets: 'Yosemite (Park Service)' -> 'Yosemite'."""
    first = re.split(r" [-|–—·:] ", title or "")[0]
    return " ".join((first if keep_brackets else re.sub(r"\([^)]*\)", " ", first)).split())


def summary(text, title="", limit=320):
    """Whole sentences from the start of a text, at most `limit` characters (or one sentence, cut).
    A leading copy of the title and Wikipedia's "Appearance" menu label are skipped."""
    text = text[len(title):].lstrip() if title and text.startswith(title) else text
    text = text.removeprefix("Appearance ")
    taken = ""
    for sentence in SENTENCE_END.split(text):
        if taken and len(taken) + len(sentence) > limit:
            break
        taken = f"{taken} {sentence}".strip()
    return taken if len(taken) <= limit else taken[: limit - 1].rsplit(" ", 1)[0] + "…"


def is_kind(page, host, kind):
    """Does this page belong on the tab? all, images (has a picture), videos (embeds one), news (a news site)."""
    if kind == "images":
        return bool(page["image"])
    if kind == "videos":
        return bool(page["video"])
    if kind == "news":
        return discover.site_of(f"https://{host}") in config.NEWS_SITES
    return True


def one_per_title(pages):
    """Keep the best page of each site + title, e.g. one of an artist's many identically titled chart pages."""
    seen, kept = set(), []
    for page in pages:
        key = (urlsplit(page["url"]).netloc, (page["title"] or page["url"]).lower())
        if key not in seen:
            seen.add(key)
            kept.append(page)
    return kept


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

    def candidates(self, query, mode="full", site=None, kind="all"):
        """Best chunk per page from BM25 and/or vectors, fused with RRF. English pages of the tab's kind only."""
        depth = config.CANDIDATES * (1 if kind == "all" else 10)  # most pages have no video: look deeper
        rankings = {}
        if mode in ("bm25", "hybrid", "pagerank", "full"):
            rankings["bm25"] = bm25.keyword_search(self.conn, query, depth)
        if mode in ("vector", "hybrid", "pagerank", "full"):
            rankings["vector"] = self.vectors.search(embed.embed_query(query), depth)
        fused, ranks = rrf(rankings)
        pages, seen = [], set()
        for chunk_id in sorted(fused, key=fused.get, reverse=True):
            page = dict(self.conn.execute(CHUNK_SQL, (chunk_id,)).fetchone())
            host = urlsplit(page["url"]).netloc
            if page["doc_id"] in seen or not (page["language"] or "en").startswith("en"):
                continue
            if site and host != site and not host.endswith("." + site):
                continue
            if not is_kind(page, host, kind):
                continue
            seen.add(page["doc_id"])
            pages.append({**page, "ranks": ranks[chunk_id], "rrf": fused[chunk_id]})
        return pages

    def rerank(self, query, pages, kind="all"):
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
            if kind == "news":
                page["final_score"] += config.W_NEWS_FRESHNESS * page["freshness"]
            if page["word_count"] < config.THIN_PAGE_WORDS:
                page["final_score"] *= config.THIN_PAGE_PENALTY
        return sorted(pages, key=lambda page: page["final_score"], reverse=True)

    def search(self, query, limit=10, offset=0, site=None, mode="full", kind="all"):
        if time.monotonic() - self.refreshed_at > config.REFRESH_SECONDS:  # reloading takes seconds on a big index
            self.refresh()
        pages = self.candidates(query, mode, site, kind)
        if mode == "pagerank":  # hybrid + link authority, no cross-encoder: shows what PageRank adds on its own
            pages.sort(key=lambda page: page["rrf"] + config.W_RRF_PAGERANK * self.pagerank.get(page["doc_id"], 0.0),
                       reverse=True)
        if mode == "full":
            pages = one_per_title(self.rerank(query, pages[: config.RERANK_TOP], kind))
            if kind != "all":  # a picture or video next to an off-topic page is just noise
                pages = [page for page in pages if page["relevance"] >= config.MIN_TAB_RELEVANCE]
        return [self.to_result(page, query) for page in pages[offset : offset + limit]]

    def to_result(self, page, query):
        return {
            "url": page["url"],
            "title": page["title"] or page["url"],
            "snippet": highlight(clean_text(page["text"]) or page["text"], query),
            "image": page["image"] or None,
            "video": page["video"] or None,
            "published": (page["published"] or "")[:10] or None,
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

    def about(self, query, results):
        """An info panel for the page that is *about* the query (its title is the query), from the top results."""
        words = query_words(query)
        exact = [r for r in results[:5] if query_words(main_title(r["title"])) == words]
        loose = [r for r in results[:5] if query_words(main_title(r["title"], keep_brackets=False)) == words]
        for result in exact + loose:  # "Adele - Wikipedia" before "Adele (given name)"
            row = self.conn.execute("SELECT id, description FROM documents WHERE url = ?", (result["url"],)).fetchone()
            text = row["description"] if row and len(row["description"] or "") >= 60 else ""
            if not text and row:
                chunks = self.conn.execute(
                    "SELECT text FROM chunks WHERE doc_id = ? ORDER BY position LIMIT 2", (row["id"],)).fetchall()
                text = clean_text(" ".join(chunk["text"] for chunk in chunks))
            name = main_title(result["title"], keep_brackets=False)
            return {"title": name, "url": result["url"], "image": result["image"],
                    "summary": summary(text, main_title(result["title"])) or None}
        return None
