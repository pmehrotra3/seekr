# Seekr

A small, fully open-source **general web search engine** you can run on one machine and host yourself.
A polite crawler, SQLite storage, keyword (BM25) plus semantic (embedding) retrieval, PageRank link authority,
Reciprocal Rank Fusion, and a cross-encoder that reads each result together with your query to score its relevance.
Search through a clean web page or a REST API with API keys.

**Learn how it works step by step:** [`guide.html`](guide.html) is a frozen tutorial that builds the first version (phase 1) line by line; the code here has grown since.

Phase 1 numbers (4K developer-docs pages, 22 labelled queries; being re-measured on the ~360K-page general index):

| Search quality | MRR@10 | nDCG@10 |
|---|---|---|
| Keyword only (BM25) | 0.624 | 0.630 |
| Semantic only (embeddings) | 0.678 | 0.712 |
| Hybrid (RRF) | 0.652 | 0.694 |
| **Hybrid + relevance reranker (Seekr)** | **0.774** | **0.782** |

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

## Docker

```bash
docker compose up --build                                   # http://localhost:8000
docker compose run --rm seekr python -m seekr crawl         # and index, rank, doctor, keys create NAME
```

The database and the downloaded models live in `./data` on your disk. The container runs on the CPU: same results,
just slower. Run it natively (Quick start) to use a GPU.

Measured on an Intel Core Ultra laptop (Arc 140T iGPU, `python tools/bench_device.py`):

| device | embed chunks/s | rerank top-30 |
|---|---|---|
| CPU | 13 | 1112 ms |
| Intel Arc (XPU, fp16) | 277 | 56 ms |

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
