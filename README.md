# Seekr

A small, fully open-source **general web search engine** you can run on one machine and host yourself.
A polite crawler, SQLite storage, keyword (BM25) plus semantic (embedding) retrieval, PageRank link authority,
Reciprocal Rank Fusion, and a cross-encoder that reads each result together with your query to score its relevance.
Search through a clean web page or a REST API with API keys.

**Learn how it works step by step:** [`guide.html`](guide.html) is a frozen tutorial that builds the first version (phase 1) line by line; the code here has grown since.

Index: **378,886 pages** (2.16M chunks) from ~110 sites: news, science, health, history, philosophy, books, music,
sport, travel, food, how-to, law, finance, Wikipedia/Wiktionary/Wikivoyage, and tech docs.

Search quality on **98 hand-labelled queries** (`python -m seekr eval`; MRR@10 / nDCG@10). Weights were tuned on the
`dev` queries only. The `test` queries were not used to pick settings, but 24 of the 33 were also scored in an earlier
run (which showed the reranker not helping, and led to more `dev` queries), so treat `test` as held out, not unseen.
"All 98" includes the 65 `dev` queries, so it is optimistic.

| stage | all 98 | dev 65 | test 33 | p50 / p95, Arc GPU (all 98) | p50 / p95, CPU (test 33) |
|---|---|---|---|---|---|
| Keyword (BM25) | 0.413 / 0.470 | 0.407 / 0.465 | 0.423 / 0.480 | 99 / 414 ms | 96 / 525 ms |
| Semantic (embeddings) | 0.526 / 0.576 | 0.531 / 0.583 | 0.515 / 0.561 | 38 / 46 ms | 75 / 83 ms |
| Hybrid (RRF) | 0.494 / 0.564 | 0.507 / 0.575 | 0.470 / 0.543 | 128 / 446 ms | 185 / 598 ms |
| + PageRank | 0.546 / 0.609 | 0.572 / 0.631 | 0.495 / 0.566 | 133 / 444 ms | 174 / 592 ms |
| **+ cross-encoder (Seekr)** | **0.607 / 0.646** | **0.657 / 0.690** | **0.509 / 0.559** | 195 / 504 ms | 640 / 1052 ms |

On held-out queries the full pipeline beats keyword search clearly but only matches embeddings alone; most labels
are a single page, so a good result from another site counts as a miss. CPU latencies are for the test split.

## Quick start (Linux or macOS, Python 3.11+)

```bash
python3 -m venv .venv && source .venv/bin/activate
# PyTorch for your hardware first (pick one):
pip install torch==2.15.0+xpu --index-url https://download.pytorch.org/whl/xpu   # Intel Arc / Core Ultra GPU
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu       # CPU only
pip install torch==2.15.0                                                         # NVIDIA (Linux) or Apple GPU (macOS)
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

Other commands: `export OUT.db` (a slim copy for serving: no raw HTML, no crawl queue), `stats`, `search <words>` (search from the terminal), `eval` (measure quality),
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

## Hosting (Docker)

```bash
python -m seekr export data/serve.db     # slim copy of the index: 11.6 GB instead of 157 GB
docker compose up -d --build             # http://127.0.0.1:8000, CPU only, models baked into the image
```

Full steps, measured sizes and server requirements (8 GB RAM, 4+ cores, 20 GB disk): [`docs/DEPLOY.md`](docs/DEPLOY.md).

Measured on an Intel Core Ultra laptop (Arc 140T iGPU, `python tools/bench_device.py`):

| device | embed chunks/s | rerank top-30 |
|---|---|---|
| CPU, 12 threads | 26 | 486 ms |
| Intel Arc (XPU, fp16) | 283 | 59 ms |

## Settings

Everything is in [`seekr/config.py`](seekr/config.py) and can be overridden with environment variables, for example
`SEEKR_MAX_PAGES_PER_DOMAIN=1000`, `SEEKR_DEVICE=cpu`, `SEEKR_RERANK_MODEL=BAAI/bge-reranker-base`,
`SEEKR_PORT=9000`, `SEEKR_LOG_LEVEL=DEBUG`. See [`.env.example`](.env.example).

## How it works

```
seeds.txt → crawler → SQLite (frontier, pages) → extractor (text, chunks)
          → FTS5 BM25 index + embeddings (GPU; float16 snapshot next to the DB) + PageRank
query     → BM25 top-100 + vector top-100 → Reciprocal Rank Fusion → best chunk per page
          → cross-encoder relevance (GPU, 0–1) → final score → REST API + web page
```

Progress and design decisions: [`PROGRESS.md`](PROGRESS.md). Tests: `python -m pytest -q`.
