# Musafir

[![ci](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml/badge.svg)](https://github.com/pmehrotra3/seekr/actions/workflows/ci.yml)

A small, self-hostable web search engine: polite crawler, hybrid retrieval, link authority and neural reranking,
served through a web page and a REST API. It runs on one machine, with or without a GPU.

## How it works

1. **Crawl** pages from a list of sites, obeying `robots.txt`.
2. **Index** their text: keyword index (BM25), embeddings, and PageRank over the links.
3. **Search**: take the best keyword and embedding matches, fuse them, and let a cross-encoder rerank the top 30.
4. **Serve** results through a website (All, Images, Videos and News tabs) and a REST API.

```
src/musafir/
├── crawl/        1. crawler, site discovery, URL rules, seeds.txt
├── index/        2. text extraction, BM25, embeddings, PageRank, export
├── search/       3. ranking pipeline, evaluation, labelled queries
├── server/       4. REST API and website
├── __main__.py   the `musafir` command
├── config.py     settings
└── db.py         SQLite storage
deploy/daily.sh   nightly crawl + index refresh
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

musafir crawl     # download pages (obeys robots.txt, resumable)
musafir index     # extract text, build the keyword index, embed
musafir rank      # PageRank
musafir serve     # http://127.0.0.1:8000, API docs at /docs
```

Other commands: `search`, `eval`, `stats`, `keys`, `export`, `daily` (one day of crawling within limits), `discover`,
`live`, `archive`, `wikipedia` and `dailymotion` (below).
Settings are in [config.py](src/musafir/config.py); override any with an environment variable, such as `MUSAFIR_DEVICE=cpu`.

## API

Live at **[seekr.pranavmehrotra.com](https://seekr.pranavmehrotra.com)**: get a free key on the home page
(no account), then:

```bash
curl -H "Authorization: Bearer $KEY" "https://seekr.pranavmehrotra.com/api/v1/search?q=black+holes&limit=3"
```

Results include title, link, snippet, preview image, video, date and ranking signals. Add `kind=images`, `videos`
or `news` for one type of result. Also `/api/v1/page` and `/api/v1/stats`;
reference at [/docs](https://seekr.pranavmehrotra.com/docs). Each key may make 60 requests per minute. On your own
instance, `musafir keys create NAME` makes a key from the command line.

## Hosting

```bash
musafir export data/serve.db             # only what search needs
docker compose up -d --build           # http://127.0.0.1:8000 (other port: MUSAFIR_HOST_PORT=…)
docker compose exec musafir musafir keys create my-app
```

To move to a server, copy `data/serve.db*` into its `data/` folder and put an HTTPS reverse proxy in front. The container
listens on localhost and believes `X-Forwarded-For` only from local hops (`MUSAFIR_TRUSTED_PROXIES`), so visitors cannot fake their IP to dodge rate limits.

On a 16-core Intel laptop, CPU only, the 379K-page index takes 13 GB of disk and about 4 GB of RAM.
API keys live in `data/keys.db`, apart from the index, so replacing the index keeps them.

### Daily refresh

`musafir daily data/serve-next.db` crawls up to `MUSAFIR_NEW_PAGES_PER_DAY` new pages (default 20,000), fetches the
`MUSAFIR_RECRAWL_PER_DAY` least recently fetched pages again (default 5,000; changed pages are re-indexed, gone ones
removed), re-indexes, ranks and exports. [deploy/daily.sh](deploy/daily.sh) runs that and swaps the new index in
(about 10 seconds of downtime). Schedule it with cron:

```bash
17 3 * * *  /path/to/musafir/deploy/daily.sh > /path/to/musafir/data/daily.log 2>&1
```

It also adds each Dailymotion channel's trending and newest videos. Set `MUSAFIR_ARCHIVE_DB` (in `.env`) to a file on
a big, slow disk and it moves the HTML of indexed pages there: over 90% of the crawl database, never read again.
`musafir archive FILE --vacuum` does that once by hand and shrinks the crawl database file.

To crawl nonstop instead, run `musafir crawl --forever` as the service in
[deploy/musafir-crawler.service](deploy/musafir-crawler.service) (pinned to four efficiency cores; pauses below
`MUSAFIR_MIN_FREE_GB` of free disk, finds new sites every 6 hours). While it runs, `daily` only indexes and refreshes.

### Sources besides crawling

- **Wikipedia:** `musafir wikipedia enwiki-latest-pages-articles.xml.bz2` reads the official
  [dump](https://dumps.wikimedia.org/enwiki/latest/) (26 GB): every article's opening, infobox facts and picture,
  one chunk per article. Then `musafir index`.
- **Dailymotion:** `musafir dailymotion` adds videos from verified publishers via the public API (no key):
  13 channels plus the searches in [video_topics.txt](src/musafir/crawl/video_topics.txt).

## Results

378,886 pages, 2.16M chunks, 98 hand-labelled queries. Values are MRR@10 / nDCG@10 from `musafir eval`.
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
