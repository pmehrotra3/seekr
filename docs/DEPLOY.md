# Deploying Seekr

Build the index on a machine with a GPU (or patience), then copy a slim export to any server and run it in Docker.
The server never crawls or embeds pages and never downloads models; it only answers searches.

## 1. Build the index (once, on your own machine)

```bash
python -m seekr crawl        # polite and resumable; run it as long as you like
python -m seekr index        # extract text, keyword index, embeddings (GPU: cuda / xpu / mps)
python -m seekr rank         # PageRank
python -m seekr export data/serve.db
```

`export` keeps only what search needs: English pages with text, their chunks, the keyword index (contentless FTS5),
vectors, PageRank and site scores. It also writes `data/serve.db.vectors.npy` and `data/serve.db.ids.npy`.

Measured for this repository's index (2026-11-23):

| | crawl database | export |
|---|---|---|
| pages | ~393K crawled | 376,958 searchable |
| chunks | 2.15M | 2,150,807 |
| size | 157 GB (mostly raw HTML) | 11.6 GB + 1.65 GB vectors |
| time | | 6 min 23 s (peak RAM 4.9 GB) |

## 2. Copy it to the server

```bash
rsync -avP data/serve.db data/serve.db.vectors.npy data/serve.db.ids.npy  server:seekr/data/
git clone <this repo> && cd seekr     # on the server, next to that data/ folder
```

## 3. Run it

```bash
docker compose up -d --build                         # http://127.0.0.1:8000 on the server (health: /healthz)
docker compose exec seekr python -m seekr keys create my-app    # API key for /api/v1
```

The image (2.55 GB) has CPU-only PyTorch and both models baked in. The `data/` volume must be writable
(SQLite keeps its WAL files there and API keys live in the database).

Measured in the container on CPU (Core Ultra laptop, 12 threads, full 377K-page index):
ready **6 s** after start, **3.6 GiB** RAM, searches **0.54–0.97 s** (8 queries, warm).

## Server size

- **RAM:** 8 GB (3.6 GB for the process + OS page cache for the database). 4 GB will swap.
- **CPU:** 4+ cores. Reranking the top 30 results took 0.73 s on 4 threads of the machine above; set
  `SEEKR_RERANK_TOP=10` to roughly halve search time for a small quality cost (dev MRR@10 0.713 → 0.709).
- **Disk:** 20 GB free (13.3 GB index + 2.6 GB image).
- **GPU:** not needed for serving.

## Behind a reverse proxy (HTTPS)

The compose file publishes port 8000 on 127.0.0.1 only. Put Caddy or nginx in front and forward to it. The container trusts `X-Forwarded-For`
(`SEEKR_TRUSTED_PROXIES=*`), so the per-visitor rate limit (30 searches/minute on the website, 60/minute per API key)
sees real visitor IPs. If port 8000 is reachable directly from the internet, set `SEEKR_TRUSTED_PROXIES` to your
proxy's IP instead, or anyone could fake their IP.

Example Caddyfile:

```
search.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## Updating the index

Rebuild and export on your machine, copy the three files over, then `docker compose restart`.
