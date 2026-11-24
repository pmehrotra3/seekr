"""Command-line entry point: python -m seekr <command>."""
import argparse
import asyncio
import logging
import sqlite3
import threading
import time

from seekr import api, config, crawler, db, discover, embed, evaluate, export, extract, index, rank, search, web

log = logging.getLogger("seekr.live")


def print_host_stats(conn):
    print(f"{'host':26} {'done':>5} {'queued':>7} {'failed':>7} {'error':>6} {'blocked':>8}")
    for r in db.host_stats(conn):
        print(f"{r['host']:26} {r['done']:5} {r['queued']:7} {r['failed']:7} {r['error']:6} {r['blocked']:8}")


def cmd_crawl(args):
    """Crawl seeds.txt plus discovered sites, or only the sites in --seeds FILE."""
    conn = db.connect()
    seeds = config.read_seeds(args.seeds) if args.seeds else config.read_seeds() + discover.found_seeds(conn)
    asyncio.run(crawler.crawl(seeds, conn))
    print_host_stats(conn)


def cmd_index(args):
    conn = db.connect()
    print("Extracting text from crawled pages:")
    counts = extract.index_pages(conn)
    print(f"new: {counts['new']}  duplicates: {counts['duplicate']}  no main text: {counts['empty']}")
    print(f"Keyword index: added {index.build_index(conn)} chunks")
    print(f"Embedding chunks on {embed.best_device()}:")
    print(f"embedded: {embed.embed_chunks(conn)}")


def cmd_rank(args):
    conn = db.connect()
    pages, links = rank.compute_pagerank(conn)
    print(f"PageRank over {pages} pages and {links} links. Top 10:")
    top = conn.execute(
        "SELECT r.score, d.url FROM pagerank r JOIN documents d ON d.id = r.doc_id ORDER BY r.score DESC LIMIT 10"
    )
    for row in top:
        print(f"  {row['score']:.5f}  {row['url']}")


def cmd_discover(args):
    conn = db.connect()
    print(f"Site importance: {discover.compute_sites(conn)} sites are linked from our pages")
    for seed in discover.discover(conn, config.read_seeds()):
        print(f"  new site to crawl: {seed}")


def crawl_forever():
    """Crawl in rounds of CRAWL_ROUND seconds, so each round also crawls the sites discovered meanwhile."""
    while True:
        try:
            conn = db.connect()
            before = conn.execute("SELECT MAX(rowid) FROM pages").fetchone()[0]  # COUNT(*) would read every page
            seeds = config.read_seeds() + discover.found_seeds(conn)
            asyncio.run(crawler.crawl(seeds, conn, until=time.monotonic() + config.CRAWL_ROUND))
            if conn.execute("SELECT MAX(rowid) FROM pages").fetchone()[0] == before:
                time.sleep(config.LIVE_INTERVAL)  # nothing new to fetch: wait for discover to find more sites
        except sqlite3.OperationalError as error:  # "database is locked": the indexer wrote for too long
            log.warning("crawl round stopped (%s); starting a new one", error)


def cmd_live(args):
    """Crawl forever in a background thread. Every LIVE_INTERVAL: index, rank and discover new sites."""
    crawling = threading.Thread(target=crawl_forever, daemon=True)
    crawling.start()
    while True:
        try:
            cmd_index(args)
            cmd_rank(args)
            cmd_discover(args)
        except sqlite3.OperationalError as error:  # "database is locked": the crawler wrote for too long
            log.warning("index round stopped (%s); trying again later", error)
        if not crawling.is_alive():
            break
        crawling.join(timeout=config.LIVE_INTERVAL)  # wait, but wake up early if the crawl thread stops


def cmd_search(args):
    engine = search.SearchEngine(db.connect())
    for i, result in enumerate(engine.search(" ".join(args.query)), start=1):
        print(f"{i:2}. [{result['relevance']:.2f}] {result['title']}\n    {result['url']}")


def cmd_eval(args):
    engine = search.SearchEngine(db.connect())
    queries = evaluate.load_queries()
    if args.split:
        queries = [item for item in queries if item.get("split") == args.split]
    print(f"{len(queries)} queries on {embed.best_device()}")
    print(f"{'stage':10} {'MRR@10':>7} {'nDCG@10':>8} {'p50 ms':>7} {'p95 ms':>7}")
    engine.search("warm up", mode="full")  # loads the models
    for mode, (mrr, ndcg, p50, p95) in evaluate.evaluate(engine, queries).items():
        print(f"{mode:10} {mrr:7.3f} {ndcg:8.3f} {p50:7.0f} {p95:7.0f}")


def cmd_serve(args):
    import uvicorn

    print(f"Seekr on http://{config.HOST}:{config.PORT}  (search page: /, API docs: /docs)")
    # Behind a reverse proxy, trust its X-Forwarded-For so rate limits see each visitor's real IP
    uvicorn.run(web.create_site(), host=config.HOST, port=config.PORT,
                proxy_headers=True, forwarded_allow_ips=config.TRUSTED_PROXIES)


def cmd_keys(args):
    key = api.create_key(db.connect(), args.name, admin=args.admin)
    print(f"New {'admin ' if args.admin else ''}API key for {args.name!r} (shown once, store it safely):\n{key}")


def cmd_stats(args):
    seeds = config.read_seeds()
    db_state = "exists" if config.DB_PATH.exists() else "not created yet"
    print(f"seeds:    {len(seeds)}")
    print(f"database: {config.DB_PATH} ({db_state})")
    if config.DB_PATH.exists():
        conn = db.connect()
        print_host_stats(conn)
        for table in ("pages", "documents", "chunks", "embeddings"):
            print(f"{table + ':':10} {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")


def cmd_export(args):
    counts = export.export(db.connect(), args.out)
    print(f"Wrote {args.out}: " + ", ".join(f"{table} {count:,}" for table, count in counts.items()))


COMMANDS = {
    "crawl": cmd_crawl,
    "index": cmd_index,
    "rank": cmd_rank,
    "discover": cmd_discover,
    "live": cmd_live,
    "serve": cmd_serve,
    "stats": cmd_stats,
    "search": cmd_search,
    "eval": cmd_eval,
    "keys": cmd_keys,
    "export": cmd_export,
}


def main(argv=None):
    logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    # progress bars, one line per HTTP request, offline-mode notices
    for noisy in ("sentence_transformers", "httpx", "httpx2", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="seekr", description="Seekr search engine")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        command = sub.add_parser(name)
        if name == "crawl":
            command.add_argument("--seeds", help="crawl only the sites in this file (default: seeds.txt + discovered)")
        if name == "eval":
            command.add_argument("--split", choices=["dev", "test"], help="only the dev (tuning) or test queries")
        if name == "export":
            command.add_argument("out", help="new database file for serving (no HTML, no crawl queue)")
        if name == "search":
            command.add_argument("query", nargs="+")
        if name == "keys":
            command.add_argument("action", choices=["create"])
            command.add_argument("name", help="who or what the key is for")
            command.add_argument("--admin", action="store_true", help="may add seeds")
    args = parser.parse_args(argv)
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
