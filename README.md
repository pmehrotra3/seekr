# Seekr

[![ci](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml/badge.svg)](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml)

A small, self-hostable web search engine: polite crawler, hybrid retrieval, link authority and neural reranking,
served through a web page and a REST API. It runs on one machine, with or without a GPU.

## How it works

1. **Crawl** pages from a list of sites, obeying `robots.txt`.
2. **Index** their text: keyword index (BM25), embeddings, and PageRank over the links.
3. **Search**: take the best keyword and embedding matches, fuse them, and let a cross-encoder rerank the top 30.
4. **Serve** results through a website and a REST API.

```
src/seekr/
├── crawl/        1. crawler, site discovery, URL rules, seeds.txt
├── index/        2. text extraction, BM25, embeddings, PageRank, export
├── search/       3. ranking pipeline, evaluation, labelled queries
├── server/       4. REST API and website
├── __main__.py   the `seekr` command
├── config.py     settings
└── db.py         SQLite storage
tests/
```

## Quick start

Python 3.11+. Install PyTorch for your hardware first; the index URL selects the build.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu         # CPU
# pip install torch==2.15.0+xpu --index-url https://download.pytorch.org/whl/xpu   # Intel Arc
# pip install torch==2.15.0                                                        # NVIDIA or Apple
pip install -e .

seekr crawl     # download pages (obeys robots.txt, resumable)
seekr index     # extract text, build the keyword index, embed
seekr rank      # PageRank
seekr serve     # http://127.0.0.1:8000, API docs at /docs
```

Other commands: `search`, `eval`, `stats`, `keys`, `export`, `discover` and `live` (crawl and index continuously).
Settings are in [config.py](src/seekr/config.py); override any with an environment variable, such as `SEEKR_DEVICE=cpu`.

## API

Live at **[seekr.pranavmehrotra.com](https://seekr.pranavmehrotra.com)**: get a free key on the home page
(no account), then:

```bash
curl -H "Authorization: Bearer $KEY" "https://seekr.pranavmehrotra.com/api/v1/search?q=black+holes&limit=3"
```

Results include title, link, snippet, preview image and ranking signals. Also `/api/v1/page` and `/api/v1/stats`;
reference at [/docs](https://seekr.pranavmehrotra.com/docs). Each key may make 60 requests per minute. On your own
instance, `seekr keys create NAME` makes a key from the command line.

## Hosting

```bash
seekr export data/serve.db             # only what search needs
docker compose up -d --build           # http://127.0.0.1:8000 (other port: SEEKR_HOST_PORT=…)
docker compose exec seekr seekr keys create my-app
```

To move to a server, copy `data/serve.db*` into its `data/` folder and put an HTTPS reverse proxy in front. The container
listens on localhost and trusts `X-Forwarded-For`; if you expose it directly, set `SEEKR_TRUSTED_PROXIES` to your proxy's IP.

On a 16-core Intel laptop, CPU only, the 379K-page index takes 13 GB of disk and about 4 GB of RAM.

## Results

378,886 pages, 2.16M chunks, 98 hand-labelled queries. Values are MRR@10 / nDCG@10 from `seekr eval`.
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
