# Seekr

A small, fully open-source search engine for **developer documentation and engineering blogs**, without SEO spam.
It runs on your own laptop: a polite crawler, SQLite storage, keyword (BM25) plus semantic (embedding) retrieval,
and a **relevance score** from a cross-encoder model that reads each result together with your query.
Search through a clean web page or a REST API with API keys.

**Build it yourself, line by line:** open [`guide.html`](guide.html) in a browser.

| Search quality (22 labelled queries) | MRR@10 | nDCG@10 |
|---|---|---|
| Keyword only (BM25) | 0.624 | 0.630 |
| Semantic only (embeddings) | 0.678 | 0.712 |
| Hybrid (RRF) | 0.652 | 0.694 |
| **Hybrid + relevance reranker (Seekr)** | **0.774** | **0.782** |

## Quick start (macOS, Python 3.11+)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m seekr crawl     # politely download pages from seeds.txt (about 10 minutes, resumable)
python -m seekr index     # clean text, chunks, keyword index, embeddings (uses the GPU if there is one)
python -m seekr rank      # PageRank over the link graph
python -m seekr serve     # http://127.0.0.1:8000  (search page)  and  /docs  (API docs)
```

Check that everything is in place at any time:

```bash
python -m seekr doctor
```

Other commands: `stats`, `search <words>` (search from the terminal), `eval` (measure quality),
`keys create NAME [--admin]` (API keys).

## The REST API

Create a key (it is shown once, and only its hash is stored):

```bash
python -m seekr keys create my-app
export KEY=sk_...   # the key it printed
```

Search:

```bash
curl -s -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/api/v1/search?q=rust+ownership&limit=3"
```

```json
{"query": "rust ownership", "took_ms": 87, "results": [
  {"url": "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
   "title": "What is Ownership? - The Rust Programming Language",
   "snippet": "What Is <mark>Ownership</mark>? <mark>Ownership</mark> is a set of rules that govern...",
   "relevance": 0.9994, "final_score": 0.96,
   "signals": {"bm25_rank": 3, "vector_rank": 2, "relevance": 0.9994, "pagerank": 0.28, "freshness": 0.26}}]}
```

More endpoints:

```bash
curl -s -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/api/v1/search?q=concurrency&site=eli.thegreenplace.net"
curl -s -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/api/v1/page?url=https://www.sqlite.org/fts5.html"
curl -s -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/api/v1/stats"
# admin keys only (python -m seekr keys create me --admin):
curl -s -X POST -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" \
     -d '{"urls": ["https://go.dev/blog/"]}' "http://127.0.0.1:8000/api/v1/crawl/seeds"
```

Each key may make 60 requests per minute (`429 Too Many Requests` after that). Interactive docs: http://127.0.0.1:8000/docs.

## Docker

```bash
docker compose up --build                                   # http://localhost:8000
docker compose run --rm seekr python -m seekr crawl         # and index, rank, doctor, keys create NAME
```

The database and the downloaded models live in `./data` on your disk. Docker on a Mac cannot use the Apple GPU,
so inside the container everything runs on the CPU: same results, but a search takes about 1.3–1.5 s instead of
~0.1 s. Run it natively (Quick start) to use the GPU.

## Settings

Everything is in [`seekr/config.py`](seekr/config.py) and can be overridden with environment variables, for example
`SEEKR_MAX_PAGES_PER_DOMAIN=1000`, `SEEKR_DEVICE=cpu`, `SEEKR_RERANK_MODEL=BAAI/bge-reranker-base`,
`SEEKR_PORT=9000`, `SEEKR_LOG_LEVEL=DEBUG`.

## How it works

```
seeds.txt → crawler → SQLite (frontier, pages) → extractor (text, chunks)
          → FTS5 BM25 index + embeddings (GPU) + PageRank
query     → BM25 top-100 + vector top-100 → Reciprocal Rank Fusion → best chunk per page
          → cross-encoder relevance (GPU, 0–1) → final score → REST API + web page
```

Progress and design decisions: [`PROGRESS.md`](PROGRESS.md). Tests: `python -m pytest -q`.
