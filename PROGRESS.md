# Seekr — build progress

Guide: open `guide.html` in a browser. Guide check: `python tools/check_guide.py`.

## Milestones
- [x] 1. Skeleton (package, config, CLI, seeds, tests, guide ch 0–1, guide checker)
- [x] 2. Crawler (async, polite, resumable; 4,086 pages crawled)
- [x] 3. Extraction and chunking (3,884 docs, 28,841 chunks)
- [x] 4. Keyword index (FTS5 / BM25; 28,841 chunks in 4 s; queries 0.4–25 ms)
- [x] 5. Embeddings on the GPU (MPS, fp16; 28,841 vectors in 4m14s; search 1.4 ms) — done before 4 at user request
- [x] 6. PageRank (3,885 pages, 165,530 links; CPU numpy, <1 s)
- [x] 7. Hybrid retrieval + relevance score + eval (full: MRR@10 0.774, nDCG@10 0.782; ~110–215 ms/query)
- [x] 8. REST API (FastAPI, hashed Bearer keys, 60/min sliding-window limit, CORS, /docs; ~100–210 ms/search)
- [x] 9. Web UI (http://127.0.0.1:8000/ — plain HTML/CSS/JS, key-less /ui/search, dark mode, mobile)
- [x] 10. Hardening (logging, `doctor`, Dockerfile + compose verified in Docker, README)

## Log

### Iteration 1 — 2026-11-14 — Milestone 1 done
- Created: `seeds.txt` (15 seeds), `requirements.txt` (pytest only; deps are added per chapter),
  `.gitignore`, `README.md`, `seekr/__init__.py`, `seekr/config.py` (env-driven settings + `read_seeds`),
  `seekr/__main__.py` (argparse CLI: crawl/index/rank/serve are stubs, `stats` works),
  `tests/test_cli.py`, `tools/check_guide.py`, `guide.html` (map, folder tree, build order, ch 0, ch 1, appendix).
- Robots.txt check of all 15 seeds with UA `SeekrBot/0.1`: all allowed, no crawl-delay set.
  eli.thegreenplace.net returns 404 for robots.txt (= everything allowed). No seeds replaced.
- Verified: `pytest -q` → 4 passed; `python -m seekr stats` → "seeds: 15";
  `tools/check_guide.py` → 8 files, 0 problems; also confirmed it exits 1 when a file drifts.
- Environment: `.venv` uses Python 3.13.2 (guide asks for 3.11+).
- Guide convention: full-file listings are `<pre data-file="path">` (checked). Partial before/after
  snippets must NOT use `data-file` (use `class="snippet"`). Code inside guide.html is HTML-escaped.
- Known issues: none.

### Iteration 2 — 2026-11-14 — Milestone 2 done
- Added `httpx==0.28.1`; crawler settings in `config.py` (MAX_DEPTH 3, MAX_PAGES_PER_DOMAIN 300,
  CRAWL_DELAY 1s, REQUEST_TIMEOUT 15s, MAX_PAGE_BYTES 2MB, RETRIES 2).
- New: `seekr/db.py` (frontier + pages tables, helpers), `seekr/urls.py` (normalize, scopes),
  `seekr/crawler.py` (one asyncio task per host, robots.txt + crawl-delay, streaming size limit,
  retries with exponential backoff, title/link parsing incl. iframes), `crawl` + per-host `stats` in CLI.
- Tests: `tests/test_urls.py` (3) + `tests/test_crawler.py` (9) using `httpx.MockTransport` → 16 passed total.
- Real crawl (2 runs, ~15 min total): 4,086 pages, ~260 MB DB. Per host: 300 for most; rust book 114
  (whole book), danluu 180, go.dev/doc 192 (their in-scope sections are fully crawled).
- Bugs found by the real crawl and fixed (each with a test):
  1. A network blip marked ~40 pages/host as permanently failed → new `error` status, requeued next run.
  2. Unreachable robots.txt marked all pages `blocked` forever → host is skipped for this run only.
  3. Django seed `/en/stable/` redirects to `/en/6.1/` → redirected seeds extend the scope
     (also restored on restart via `db.redirect_targets`).
  4. Rust book TOC is in an `<iframe src="toc.html">` → crawler follows iframe src.
  One-time data repair: deleted django/rust rows and requeued old `failed` rows, then re-crawled.
- Guide: chapter 2 (11 steps, checkpoint with real stats, common errors), map/tree/build order updated.
  `tools/check_guide.py` → 13 files, 0 problems.
- DECISION (user request mid-iteration: "GPU accelerated everything"): machine is Apple M4 Pro.
  Milestone 5 will use sentence-transformers + torch (device auto: cuda → mps → cpu) instead of
  fastembed (CPU-only on Mac). Same model BAAI/bge-small-en-v1.5. Reranker (milestone 7) and vector
  search (torch matmul) also on that device. Crawling (network-bound) and BM25 (SQLite) stay CPU —
  GPU can't speed those up. PageRank on ~4k–100k nodes is milliseconds in numpy; keep CPU.
- Known issues: none blocking. Frontier has ~20k queued URLs beyond the 300/host cap (expected).

### Iteration 3 — 2026-11-14 — Milestone 3 done
- Added `trafilatura==2.3.1`; `CHUNK_WORDS=300`, `CHUNK_OVERLAP=50` in config.
- New tables `documents` (one row per page; `duplicate_of` for content-hash duplicates; word_count 0 for
  pages with no main text) and `chunks` (doc_id, position, text).
- New `seekr/extract.py`: trafilatura JSON extraction, title from the crawler's `<title>` (trafilatura
  gives a generic title on mdBook pages), description from `excerpt`, language from `<html lang>`
  (trafilatura's language field was always empty), strips Sphinx `¶`; overlapping word chunks;
  SHA-256 content hash; incremental `index_pages` with a ProcessPoolExecutor (batches of 200).
- CLI: `index` runs extraction; `stats` prints pages/documents/chunks counts.
- Tests: `tests/test_extract.py` (5) → 21 passed total.
- Real run: 4,086 pages → 3,884 new docs, 201 duplicates, 1 with no main text; 28,841 chunks;
  51 s wall clock on M4 Pro (~6 cores busy). Average doc 1,767 words. Re-run is a no-op.
- Guide: chapter 3 (9 steps + checkpoint), tree/map/build order updated; check → 15 files, 0 problems.
- Known issues (to handle in milestone 7 ranking/filtering):
  * fastapi.tiangolo.com includes translations (de/es/…); language is stored, so search should
    filter to English (`language LIKE 'en%' OR language = ''`).
  * doc.rust-lang.org/book/print.html is the whole book on one page (180k words) — near-duplicate
    of every chapter; consider down-weighting/excluding print.html-style pages.
  * 369 originals have < 100 words (thin pages) — to be penalized in milestone 7.

### Iteration 4 — 2026-11-14 — Milestone 5 done (pulled ahead of 4: user asked "make it GPU accelerated, use the GPU of this Mac")
- What can/can't use the GPU, stated to the user: crawling (network-bound), trafilatura extraction (no GPU
  support) and SQLite FTS5 stay on CPU; embeddings, vector search and (ch 7) the reranker use the GPU.
- Added `torch==2.15.0`, `sentence-transformers==6.3.0`, `numpy==2.5.4`. MPS available (M4 Pro, Metal 4).
- Benchmarks on 1,024 real chunks (bge-small-en-v1.5, ~512 tokens/chunk): CPU fp32 24/s, MPS fp32 44/s,
  MPS fp16 67/s (cosine vs fp32 = 1.0000). Raw transformers forward: sdpa 90/s vs eager 64/s, so the
  GPU is compute-bound, not starved; tokenization is only 0.17 s per 512 chunks.
- New `seekr/embed.py`: `best_device()` (SEEKR_DEVICE override, cuda → mps → cpu), cached model in fp16 on
  GPU, BGE query prefix, `embed_chunks` (incremental, title + text), `VectorIndex` (all vectors in one
  torch matrix on the GPU; matmul + topk). New `embeddings` table (chunk_id, float32 BLOB).
  Config: EMBED_MODEL, EMBED_BATCH=64, DEVICE. `index` now runs extraction then embedding.
- Tests: `tests/test_embed.py` (5, includes real-model semantic check and GPU-selected check) → 26 passed.
- Real run: 28,841 chunks embedded on mps in 4 min 14 s. VectorIndex load 0.1 s, matrix (28841, 384) on mps:0;
  search 1.4 ms warm (95 ms first call).
- Sample: "run many network requests concurrently in python" → eli.thegreenplace concurrency posts (good);
  "how do I free memory without a garbage collector" → go.dev gc-guide x4 (rust ownership missing) —
  motivates per-page grouping + cross-encoder reranking in milestone 7.
- Guide: chapter 5 (10 steps, CPU vs GPU table, checkpoint with real output); check → 17 files, 0 problems.
- Known issues: HF Hub prints an "unauthenticated requests" warning (harmless; model is cached after first
  download). Milestone 4 is still open.

### Iteration 5 — 2026-11-14 — Milestone 4 done
- New `seekr/index.py`: FTS5 virtual table `chunks_fts(title, text)` with `porter unicode61` tokenizer,
  rowid = chunk id; incremental `build_index` (INSERT…SELECT where id > MAX(rowid)); `to_fts_query`
  (keeps \w+ words, quotes each, joins with OR — no FTS syntax injection); `keyword_search` with
  `bm25(chunks_fts, 5.0, 1.0)` (title 5x), returns positive scores. FTS table is created by index.py, so
  db.py/config.py did not change. `index` command: extract → keyword index → embed.
- Tests: `tests/test_index.py` (5: escaping, title weighting, stemming, incremental, empty) → 31 passed.
- Real run: 28,841 chunks indexed in ~4 s; DB now 524 MB. Sample top hits: "rust ownership" → Rust book
  ch04 (good); "css flexbox" → MDN flexbox basic concepts (good); "fastapi dependency injection" →
  tutorial/dependencies (good); "sqlite full text search" → fts3.html then fts5.html (ok);
  "postgres indexes" → bookindex.html + django genindex (BAD: index pages; for the reranker to fix).
- Guide: chapter 4 (6 steps + checkpoint). Because ch 5 was written first, ch 4 shows an intermediate
  `seekr/__main__.py` (without embeddings) via a renderer snapshot; ch 5's listings now include ch 4's
  changes and its "do this chapter first" callout was removed, so the guide builds linearly 0→5.
  check → 19 files, 0 problems.
- Guide tooling note: guide.html is rendered from a template kept in the session scratchpad
  (`@@FILE:path@@` = real file, `@@SNAP:path=file@@` = earlier version). If the template is lost,
  edit guide.html directly; `tools/check_guide.py` still guards the final listings.

### Iteration 6 — 2026-11-14 — Milestone 6 done
- New `seekr/rank.py`: `link_graph` (pages.outlinks → document graph; redirects via final_url; duplicates
  mapped to their original; self-links dropped; edges deduped), `pagerank` (numpy power iteration,
  d = 0.85, dangling mass spread evenly, tolerance 1e-10), `compute_pagerank` (rebuilds `pagerank` table;
  schema lives in rank.py like FTS in index.py, db.py unchanged). CLI `rank` prints the top 10.
- Tests: `tests/test_rank.py` (5: cycle, star/dangling/sum-to-1, hand-worked formula, redirect + duplicate
  merging, storage) → 36 passed.
- Real run: 3,885 docs, 165,530 links, scores sum to 1.0. Top: paulgraham.com/index.html, jvns.ca/,
  postgresql.org/docs/current/, jvns.ca/about. Per-site totals ≈ proportional to page count — in a focused
  crawl PageRank mostly measures intra-site hubs. Rust ownership ch rank 693; postgres indexes.html 883
  vs bookindex.html 737 — PageRank does not fix the index-page problem (reranker must).
- CPU on purpose (tiny graph). `python -m seekr rank` takes ~5 s, mostly importing torch via __main__.
- Preview: a temporary hybrid (BM25 + GPU vectors, RRF) search page runs from the session scratchpad on
  http://127.0.0.1:8765 for the user to try; not part of the project/guide.
- Guide: chapter 6 (5 steps + checkpoint); check → 21 files, 0 problems.
- User asked about indexing all of Common Crawl — scope discussion pending (see chat); not started.

### Iteration 7 — 2026-11-14 — Milestone 7 done
- New `seekr/search.py` (139 lines): `rrf` (k=60), `SearchEngine.candidates` (BM25 top-100 + GPU vector
  top-100 → RRF → best chunk per page, English-only, optional `site` filter incl. subdomains),
  `rerank` (cross-encoder on mps fp16, raw logits → our own sigmoid = calibrated 0–1 relevance; final =
  0.90·relevance + 0.05·log-normalized PageRank + 0.0·freshness + 0.05·exact title/URL word match; pages
  < 50 words ×0.8), `highlight` (escapes page text, then <mark>), `freshness`, `search(query, limit, offset,
  site, mode)` with modes bm25 / vector / hybrid / full, results incl. `signals`.
- New `seekr/evaluate.py` (MRR@10, nDCG@10 over 4 modes), `evals/queries.jsonl` (22 queries: 14 keyword-style,
  8 natural-language; every expected URL verified to exist in the index). CLI: `search <words>`, `eval`.
- Tests: `tests/test_search.py` (7, incl. a real 3-page end-to-end engine), `tests/test_evaluate.py` (3) → 46 passed.
- EVAL (22 queries):            MRR@10  nDCG@10
    bm25                         0.624    0.630
    vector                       0.678    0.712
    hybrid (RRF)                 0.652    0.694
    full (hybrid + rerank)       0.774    0.782
- DEVIATIONS FROM SPEC, backed by the eval (documented in guide ch 7 "What the measurements taught us"):
  * Reranker default = cross-encoder/ms-marco-MiniLM-L-6-v2, not BAAI/bge-reranker-base: relevance-only MRR
    0.733 vs 0.648, and 0.4 s vs 1.2 s per 50 pairs on mps fp16. bge still selectable via SEEKR_RERANK_MODEL.
  * Weights 0.90/0.05/0.0/0.05 instead of 0.75/0.15/0.05/0.05 (spec weights gave MRR 0.522 — worse than
    vector-only). PageRank 0.15 promoted hubs + print.html; freshness misleads on docs ("last updated today").
  * Rerank top 30 (top 50 was worse: 0.714). Thin penalty softened to <50 words ×0.8.
  * Near-duplicate penalty (embedding cos > 0.95/0.97/0.99) had no measurable effect → removed (minimal code);
    exact duplicates are already dropped at index time.
- Latency (warm, M4 Pro): candidates 32–125 ms + rerank 76–91 ms on mps.
- Spot checks: "postgres indexes" → indexes.html #1 (BM25 had bookindex.html); "rust ownership" → ch04-01 #1;
  "how do I free memory without a garbage collector" → go gc-guide #1, rust ch04-01 #2.
- Guide: chapter 7 (10 steps, experiments table, honest caveat about tuning on 22 queries); check → 26 files, 0 problems.
- Preview page (scratchpad, http://127.0.0.1:8765) now uses the real SearchEngine with relevance badges.
- Known issues: eval is small and tuned on itself (needs a held-out set); doc.rust-lang.org/book/print.html still
  appears (relevant content, #3 for "rust ownership").

### Iteration 8 — 2026-11-14 — Milestone 8 done
- Added `fastapi==0.163.0`, `uvicorn==0.54.0`; config RATE_LIMIT_PER_MINUTE=60, CORS_ORIGINS="*".
- New `seekr/api.py` (≈180 lines, mostly Pydantic models): `create_key` (secrets.token_urlsafe(24), stores
  sha256 only), `RateLimiter` (per-key deque sliding window), models Signals/Result/SearchResponse/Page/Seeds,
  `api_key` / `admin_key` dependencies (HTTPBearer → 401/403/429 + Retry-After), routes under /api/v1:
  GET /search (q 1–200 chars, limit 1–30, offset 0–29, site), GET /page?url=, GET /stats, POST /crawl/seeds
  (admin; normalizes + dedupes, appends to seeds.txt). `create_app(db_path)` factory with lifespan (opens DB,
  builds SearchEngine, warm-up search), CORSMiddleware. CLI: `serve` (uvicorn), `keys create NAME [--admin]`;
  removed the unused `not_built_yet` placeholder.
- Bug found & fixed: sync `def` dependency ran in FastAPI's threadpool → sqlite3.ProgrammingError (connection
  used from another thread). All handlers/dependencies are `async def` → single thread. Documented in guide.
- Small fixes: first request took 1.5 s (MPS kernel compile) → warm-up search in lifespan, now 141 ms;
  snippets started mid-word ("…xpert") → start on a word boundary in `search.highlight` (+1 test).
- Tests: `tests/test_api.py` (9, TestClient incl. lifespan; reuses PAGES from test_search) → 56 passed.
- Real run: `keys create demo`, `serve` on 127.0.0.1:8000; curl verified 401 without key, search (postgres
  indexes → indexes.html, bm25_rank null / vector_rank 1), site filter (eli.thegreenplace.net, 213 ms), stats
  (4086/3884/28841/28841/mps), page (fts5.html, 91 chunks), 403 for non-admin seeds, OpenAPI lists 4 paths.
  Server left running on :8000. Demo key saved in the session scratchpad (demo_key.txt), not in the repo.
- Guide: chapter 8 (11 steps + checkpoint, incl. the thread error we hit); ch 7 test count updated to 47;
  check → 28 files, 0 problems.

### Iteration 9 — 2026-11-14 — Milestone 9 done (+ a guide bug found and fixed)
- New `seekr/web.py` (21 lines): `create_site()` = Chapter 8 API app + key-less `GET /ui/search` (page size 10,
  rate-limited per client IP, UI_RATE_LIMIT_PER_MINUTE=30, hidden from /docs; reuses api.search_pages) +
  `StaticFiles(web/, html=True)` mounted last. api.py unchanged. `serve` now runs create_site().
- New `web/index.html` (31), `web/style.css` (79), `web/app.js` (117): wordmark + tagline, centered search box that
  moves to the top on search, results with title/URL/<mark> snippet/relevance badge (green ≥80%, amber ≥40%),
  status line with timing, Prev/Next pagination up to 30 results, URL as state (pushState + popstate), "/" to focus,
  light/dark via prefers-color-scheme + ◐ toggle saved in localStorage (try/catch), mobile layout.
  XSS: titles/URLs via textContent; only the server-escaped snippet uses innerHTML.
- Verified visually with headless Chrome screenshots (desktop dark, desktop light page 2, 390px phone via iframe).
  Bugs found that way and fixed: pager visible on the home page (`display:flex` beat `hidden` → `[hidden]{display:none
  !important}`); sideways scroll on phones (flex item min-width → `.url{min-width:0}` + wrapping meta); snippet
  highlighted "the/how/same" → STOPWORDS in search.highlight (+1 test). Note: headless Chrome's minimum window is 500px.
- Tests: `tests/test_web.py` (4) → 61 passed.
- GUIDE BUG (pre-existing since iteration 3): every chapter's "whole updated file" listing was rendered from the CURRENT
  file, so e.g. ch 2's __main__.py imported api/search/web. check_guide.py only checks the last listing per file, so it
  missed this. Fixed: rebuilt per-chapter versions of requirements.txt (ch1/2/3/5), config.py (ch1/2/3/5/7/8),
  db.py (ch2/3), __main__.py (ch1/2/3/5/6/7/8) — validated by AST (imports exist at that chapter, command table
  consistent) and by an exact-match check against the existing ch 4 snapshot.
- New `tools/replay_guide.py` (+ guide appendix): rebuilds the project from guide.html alone for each chapter in a temp
  dir and runs that stage's tests. Result: ch1 4, ch2 16, ch3 21, ch4 26, ch5 31, ch6 36, ch7 48, ch8 57, ch9 61 — all ok.
- Guide: chapter 9 (9 steps + checkpoint); ch 7/8 test counts updated (48/57); check → 34 files, 0 problems.
- Running: `python -m seekr serve` on :8000 (site + API). The scratchpad preview on :8765 is retired.

### Iteration 10 — 2026-11-14 — Milestone 10 done
- Logging: `LOG_LEVEL` setting; `logging.basicConfig` in the CLI; quiet sentence_transformers/httpx/httpx2 (progress bars
  and one line per HTTP request); crawler logs skipped hosts (warning), failures (info), per-host totals, every URL at
  DEBUG; API logs one line per search (query, offset, site, results, ms).
- New `seekr/doctor.py` + `python -m seekr doctor` (exit code 0/1): Python ≥ 3.11, packages, compute device, seeds,
  DB tables + counts + index consistency (chunks == FTS == embeddings), models cached, free disk. Each failure names the
  fix command; a crashing check can't hide the others.
- Dockerfile (python:3.12-slim, CPU-only torch from download.pytorch.org first, HF_HOME in the data volume),
  docker-compose.yml (8000:8000, ./data volume, restart), .dockerignore. VERIFIED: image built (1.5 min, 2.02 GB);
  doctor in container; server in container on :8001 downloaded models then answered searches with the same top results
  as native (rust ownership → ch04-01, postgres indexes → indexes.html) at 1.3–1.5 s/search on CPU vs ~0.09–0.2 s native
  on MPS.
- Bugs found by the real runs and fixed: doctor crashed on a fresh container (huggingface_hub CacheNotFound) → handled
  + test; my first test for it set HF_HUB_CACHE, which passed alone but failed in the full suite (env read at import) →
  rewritten to monkeypatch scan_cache_dir. README: replaced an unmeasured took_ms and a wrong "3x slower" with measured
  values (87 ms warm native; 1.3–1.5 s in Docker).
- README rewritten: eval table, quick start (crawl → index → rank → serve), doctor, API with real curl output, Docker,
  settings, pipeline diagram.
- Tests: `tests/test_hardening.py` (6) → 67 passed. Guide: chapter 10 (14 steps) + final Summary section; earlier
  chapters now show their own versions of crawler.py (ch2), api.py (ch8), config.py and __main__.py (ch9).
  check_guide → 40 files, 0 problems. replay_guide → ch1 4, ch2 16, ch3 21, ch4 26, ch5 31, ch6 36, ch7 48, ch8 57,
  ch9 61, ch10 67 — all ok.

## FINAL SUMMARY — all 10 milestones done and verified (2026-11-14)
What works:
- Polite resumable crawler (robots.txt, 1 req/s/host, retries, redirects, iframes): 4,086 pages from 15 dev-docs/blog sites.
- Extraction (trafilatura), 28,841 overlapping ~300-word chunks, SHA-256 dedupe; FTS5 BM25 (title ×5); embeddings on the
  Apple GPU (MPS fp16, 4m14s); PageRank (165,530 links).
- Hybrid retrieval (BM25 + vectors, RRF k=60) + cross-encoder relevance (MiniLM on MPS, sigmoid-calibrated 0–1) as the
  primary signal: final = 0.90 relevance + 0.05 PageRank + 0.05 exact match. ~0.09–0.2 s/search warm.
- REST API (hashed Bearer keys, 60/min per key, CORS, /docs), web UI (key-less /ui/search 30/min per IP, dark mode,
  mobile, pagination), logging, doctor, Docker.
- 67 tests; guide.html (chapters 0–10 + summary) verified by check_guide.py and replay_guide.py.
Eval (22 queries):  bm25 0.624/0.630 · vector 0.678/0.712 · hybrid 0.652/0.694 · hybrid+rerank 0.774/0.782 (MRR@10/nDCG@10).
Known limitations: eval is small and tuned on itself (add a held-out set); rust book print.html still appears as a
result; crawl capped at 300 pages/site; Docker on Mac is CPU-only.
Next phase: RAG answers with citations on top of /api/v1/search; Common Crawl import via its URL index (scoped slice,
discussed with the user); held-out evaluation.

## After the 10 milestones: growing the crawl (2026-11-14, guide chapters 11-12)

- **More seeds:** 15 → 80. All were checked with robots.txt first. Left out: nodejs.org docs, Reuters, CNN, NYT, IMDb, AllMusic and LinkedIn (robots.txt disallows bots); Wikipedia, AP, The Guardian, Britannica, CDC and others (403 for our User-Agent). Wikipedia requires contact info in the UA; the user has not decided yet.
- **`live` command:** crawls forever in 30-minute rounds in a background thread. Every 10 minutes it indexes, ranks and discovers new sites. SQLite runs in WAL mode with a 60 s busy timeout, so `serve` reads while `live` writes, and `SearchEngine.refresh()` reloads new vectors without a restart.
- **Site importance + discovery** (`seekr/discover.py`): counts the distinct other sites that link to each site, then adds the most-linked unknown sites after checking robots.txt, that the homepage is HTML and that it is English. The first real round added 9 of 20 (GitHub, W3C, arXiv, ...). `W_SITE=0.05`: MRR 0.706 → 0.716, nDCG 0.727 → 0.735.
- **Bugs found at scale, all fixed and tested:**
  - a bracketed link crashed the crawl (`ValueError: Invalid IPv6 URL`);
  - trafilatura wrote invalid JSON for one page and crashed indexing;
  - two pages redirecting to one URL caused a `KeyError` in PageRank;
  - one huge page left 13 of 14 extraction workers idle (fixed with batches of 1000 and one page per task: about 13 → 33 pages/s).
- **Numbers at 17:05:**
  - 86,490 pages crawled; 77,321 searchable; 402,180 chunks;
  - embeddings 41% done (the GPU is at 98-99%);
  - 75 tests pass; check_guide and replay_guide pass for all 12 chapters.
- **Eval drop** (0.774 → 0.716) is expected with a 20× bigger index while embeddings are incomplete. Re-measure when they finish.

## Fast searches & moving to a bigger machine (2026-11-15, guide chapter 13)
- Searches had become slow (seconds) while `live` ran: every new embedding batch made the next search reload all ~700k vectors. `search()` now reloads at most every `SEEKR_REFRESH_SECONDS` (300). Test: `test_search_reloads_at_most_every_refresh_seconds`. 77 passed; check_guide 0 problems; replay ch1-13 ok.
- The database reached 100 GB (raw HTML of 295,834 pages), filling the laptop. Moved to a Linux box over Tailscale: code + venv on its SSD (~/Search_engine), data on a 3.6 TB exFAT USB hard drive (SEEKR_DB on that drive, budget 1 TB). Verified with sha1 before deleting the laptop copy.
- Known: Wikipedia stopped at MAX_PAGES_PER_DOMAIN=5000 (e.g. Albert_Einstein still queued); the new machine runs with 100000. The DB lives on a spinning disk, so cold searches are slower until the OS caches it.
- Next: drop stored HTML after extraction to slow DB growth; skip download links (.7z, .zip, ...) before fetching.

## Phase 2 — general search engine, ~300K pages, Linux + Intel Arc, hostable (started 2026-11-22)
Target and per-run instructions: `.claude/loop-prompt.md` (not committed).
Scope change (user, 2026-11-22): **general web search, not only developer docs.**

- [ ] 11. Linux + Intel Arc port (XPU torch, device auto-detect, doctor, measured throughput)
- [ ] 12. Repo formalization (git, pyproject, ruff, LICENSE, .env.example, CI, clean data/)
- [ ] 13. General seeds + crawl to ~300K (balanced categories, ≤15% per domain; Common Crawl bootstrap allowed)
- [ ] 14. Index at scale (streaming extraction, mmap fp16 vectors, FTS5, sparse PageRank; time/size/RAM recorded)
- [ ] 15. Eval at scale (≥50 labelled queries across categories, per-stage table, p50/p95 latency XPU vs CPU)
- [ ] 16. Hosting (lean Docker CPU + optional Intel GPU, healthcheck, docs/DEPLOY.md, min VPS size)
- [ ] 17. Final polish (README matches reality, guide updated or retired, resume line from measured numbers)

### Iteration 11 — 2026-11-22 — milestones 11 and 12 (mostly)
- Machine: Ubuntu 26.04, Intel Arrow Lake-P iGPU (Arc 130T/140T), 16 cores, 61 GB RAM. Level Zero + OpenCL drivers
  already installed; user is in `render`.
- **Existing data found:** `/mnt/cherry/seekr/seekr.db` (155.6 GB + 14 GB WAL, exFAT USB HDD) from phase 1.
  `MAX(rowid) FROM pages` = 436,112. Exact counts by status/documents/chunks/embeddings: still scanning (full scans
  of 155 GB on a spinning disk). Last `live.log` lines show it was crawling `.tar.xz`/`.asc` download links
  (known waste, see "Next" in the previous phase) and embedding on **cpu**. Nothing is running now.
- **XPU:** replaced `torch 2.15.0+cu132` (useless here, no NVIDIA GPU) with `torch==2.15.0+xpu`
  (`pip install torch==2.15.0+xpu --index-url https://download.pytorch.org/whl/xpu`). `torch.xpu.is_available()` True,
  "Intel(R) Arc(TM) Graphics", 56.9 GiB shared memory; fp16 4096² matmul ok.
- `embed.best_device()`: cuda → **xpu** → mps → cpu. Test generalized to any GPU backend.
- New `tools/bench_device.py` (real numbers, bge-small, ~300-word chunks, fp16 on GPU, batch 64):

  | device | embed chunks/s | rerank top-30 (ms, median of 10) |
  |---|---|---|
  | cpu (16 threads) | 13 | 1112 |
  | xpu (Arc iGPU)   | 277 | 56 |

  → ~2M chunks ≈ 2 h on XPU. CPU number is suspiciously low for 16 cores (maybe the oneMKL/OpenMP bundled with the
  XPU wheel); investigate before quoting CPU latency in milestone 15.
- Repo: `git init` (main), `pyproject.toml` (metadata, `seekr` console script, ruff E/F/W/I/B/UP @120, B008 ignored for
  FastAPI `Depends`), ruff fixes (10 long lines wrapped, `zip(strict=False)`), MIT `LICENSE`, `.env.example`,
  `.github/workflows/ci.yml` (CPU torch, ruff, pytest, HF model cache — 3 test files load the two small models),
  `.gitignore` (+ logs, .env, .claude/), stray logs deleted from `data/`. `ruff==0.14.0` added to requirements (dev).
- Verified: `ruff check .` clean; `pytest -q` → 78 passed (on torch+xpu).
- Known issues: `tools/check_guide.py` → 18 mismatches (guide listings vs. lint-fixed files). Decide in milestone 17
  (update or retire guide.html). CI not yet run (no remote; by design).
- Next: finish DB counts → decide reuse vs. re-crawl for the general corpus (existing DB is dev-heavy + Wikipedia
  ≤5000/100000 per domain); README Linux/XPU quick start; then milestone 13.
