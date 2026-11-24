# Seekr

[![ci](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml/badge.svg)](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml)

A small, self-hostable web search engine: polite crawler, hybrid retrieval, link authority and neural reranking,
served through a web page and a REST API. It runs on one machine, with or without a GPU.

```
seeds.txt → crawler → SQLite → text chunks → BM25 index + embeddings + PageRank
query     → BM25 top 100 + vector top 100 → Reciprocal Rank Fusion → cross-encoder → results
```

## Quick start

Python 3.11+. Install PyTorch for your hardware first; the index URL selects the build.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu         # CPU
# pip install torch==2.15.0+xpu --index-url https://download.pytorch.org/whl/xpu   # Intel Arc
# pip install torch==2.15.0                                                        # NVIDIA or Apple
pip install -r requirements.txt

python -m seekr crawl     # download pages from seeds.txt (obeys robots.txt, resumable)
python -m seekr index     # extract text, build the keyword index, embed
python -m seekr rank      # PageRank
python -m seekr serve     # http://127.0.0.1:8000, API docs at /docs
```

Other commands: `search`, `eval`, `stats`, `keys`, `export`, `discover` and `live` (crawl and index continuously).
Settings are in [seekr/config.py](seekr/config.py); override any with an environment variable, such as `SEEKR_DEVICE=cpu`.

## API

```bash
python -m seekr keys create my-app     # prints a key once; only its hash is stored
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/api/v1/search?q=rust+ownership&limit=3"
```

Also `/api/v1/page` and `/api/v1/stats`. Each key may make 60 requests per minute.

## Hosting

```bash
python -m seekr export data/serve.db   # only what search needs
docker compose up -d --build           # http://127.0.0.1:8000
docker compose exec seekr python -m seekr keys create my-app
```

To move to a server, copy `data/serve.db*` into its `data/` folder and put an HTTPS reverse proxy in front. The container
listens on localhost and trusts `X-Forwarded-For`; if you expose it directly, set `SEEKR_TRUSTED_PROXIES` to your proxy's IP.

On a 16-core Intel laptop, CPU only, the 379K-page index takes 13 GB of disk and about 4 GB of RAM.

## Results

378,886 pages, 2.16M chunks, 98 hand-labelled queries. Values are MRR@10 / nDCG@10 from `python -m seekr eval`.
The index itself is not in this repository.

| Stage | dev (65) | test (33) | median, Intel Arc | median, CPU |
|---|---|---|---|---|
| BM25 | 0.407 / 0.465 | 0.423 / 0.480 | 99 ms | 96 ms |
| Embeddings | 0.531 / 0.583 | 0.515 / 0.561 | 38 ms | 75 ms |
| Hybrid (RRF) | 0.507 / 0.575 | 0.470 / 0.543 | 128 ms | 185 ms |
| + PageRank | 0.572 / 0.631 | 0.495 / 0.566 | 133 ms | 174 ms |
| + cross-encoder | 0.657 / 0.690 | 0.509 / 0.559 | 195 ms | 640 ms |

Settings were tuned on `dev` only, but 24 of the 33 `test` queries were also scored once during development. On `test`,
the full pipeline beats BM25 and roughly matches embeddings alone. Most queries have one labelled page, so a good
answer from another site counts as a miss. Arc latency is over all 98 queries, CPU latency over `test`.

## Development

```bash
pip install -e .[dev]
ruff check . && pytest -q
```

[MIT license](LICENSE)
