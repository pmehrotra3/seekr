"""All settings in one place. Override any of them with an environment variable."""
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

DB_PATH = Path(os.environ.get("MUSAFIR_DB", "data/musafir.db"))
KEYS_DB = Path(os.environ.get("MUSAFIR_KEYS_DB", "data/keys.db"))  # API keys, apart from the index that gets replaced
SEEDS_FILE = Path(os.environ.get("MUSAFIR_SEEDS", PACKAGE / "crawl" / "seeds.txt"))
CONTACT = os.environ.get("MUSAFIR_CONTACT", "")  # e.g. "Your Name; you@example.com". Some sites (Wikipedia) require it
USER_AGENT = os.environ.get("MUSAFIR_USER_AGENT", f"MusafirBot/0.1 ({CONTACT})" if CONTACT else "MusafirBot/0.1")
HOST = os.environ.get("MUSAFIR_HOST", "127.0.0.1")
PORT = int(os.environ.get("MUSAFIR_PORT", "8000"))

# Crawler
MAX_DEPTH = int(os.environ.get("MUSAFIR_MAX_DEPTH", "3"))
MAX_PAGES_PER_DOMAIN = int(os.environ.get("MUSAFIR_MAX_PAGES_PER_DOMAIN", "300"))
LIVE_INTERVAL = float(os.environ.get("MUSAFIR_LIVE_INTERVAL", "600"))  # seconds between index runs in `live`
CRAWL_ROUND = float(os.environ.get("MUSAFIR_CRAWL_ROUND", "1800"))  # `live` restarts the crawl this often (new sites)
DISCOVER_MIN_LINKS = int(os.environ.get("MUSAFIR_DISCOVER_MIN_LINKS", "3"))  # other sites that must link to a new one
DISCOVER_PER_ROUND = int(os.environ.get("MUSAFIR_DISCOVER_PER_ROUND", "20"))  # sites checked per `discover`
DISCOVER_EVERY = float(os.environ.get("MUSAFIR_DISCOVER_EVERY", "21600"))  # `crawl --forever` looks for new sites
MIN_FREE_GB = float(os.environ.get("MUSAFIR_MIN_FREE_GB", "100"))  # crawling pauses below this much free disk
CRAWL_DELAY = float(os.environ.get("MUSAFIR_CRAWL_DELAY", "1.0"))  # seconds between requests to one host
REQUEST_TIMEOUT = float(os.environ.get("MUSAFIR_REQUEST_TIMEOUT", "15"))
MAX_PAGE_BYTES = int(os.environ.get("MUSAFIR_MAX_PAGE_BYTES", "5000000"))  # long Wikipedia articles are over 2 MB
RETRIES = int(os.environ.get("MUSAFIR_RETRIES", "2"))
NEW_PAGES_PER_DAY = int(os.environ.get("MUSAFIR_NEW_PAGES_PER_DAY", "20000"))  # `daily`: pages never fetched before
RECRAWL_PER_DAY = int(os.environ.get("MUSAFIR_RECRAWL_PER_DAY", "5000"))  # `daily`: oldest pages fetched again
# `daily` moves the HTML of indexed pages here (a big, slow disk is fine). Empty: keep it in the crawl database.
ARCHIVE_DB = os.environ.get("MUSAFIR_ARCHIVE_DB", "")

# Extraction
CHUNK_WORDS = int(os.environ.get("MUSAFIR_CHUNK_WORDS", "300"))
CHUNK_OVERLAP = int(os.environ.get("MUSAFIR_CHUNK_OVERLAP", "50"))

# Wikipedia dump: words kept per article, and the fewest worth indexing
WIKI_WORDS = int(os.environ.get("MUSAFIR_WIKI_WORDS", "300"))  # = CHUNK_WORDS: one vector per article
WIKI_MIN_WORDS = int(os.environ.get("MUSAFIR_WIKI_MIN_WORDS", "40"))

# Embeddings (runs on the GPU when there is one)
EMBED_MODEL = os.environ.get("MUSAFIR_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_BATCH = int(os.environ.get("MUSAFIR_EMBED_BATCH", "64"))
# CPU threads for model math. Laptop CPUs mix fast and slow cores; using every core makes the fast ones wait
# (measured on a 16-core Core Ultra: 12 threads rerank in 0.47 s, 16 threads in 2.2 s). Small servers use all cores.
_CORES = os.cpu_count() or 1
CPU_THREADS = int(os.environ.get("MUSAFIR_CPU_THREADS") or (_CORES if _CORES <= 8 else _CORES * 3 // 4))
DEVICE = os.environ.get("MUSAFIR_DEVICE", "")  # "", "cuda", "xpu" (Intel Arc), "mps" or "cpu"; "" picks the best one

# Search and relevance scoring
CANDIDATES = int(os.environ.get("MUSAFIR_CANDIDATES", "100"))  # from each of BM25 and vectors
RERANK_TOP = int(os.environ.get("MUSAFIR_RERANK_TOP", "30"))  # pages the cross-encoder reads per query
# MiniLM beat BAAI/bge-reranker-base on our eval (MRR 0.733 vs 0.648) and is 3x faster; try either.
RERANK_MODEL = os.environ.get("MUSAFIR_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_MAX_TOKENS = int(os.environ.get("MUSAFIR_RERANK_MAX_TOKENS", "384"))
# Tuned on evals/queries.jsonl. Freshness is 0: docs show "last updated today", so dates mislead.
W_RELEVANCE, W_PAGERANK, W_FRESHNESS, W_EXACT = 0.90, 0.05, 0.0, 0.05
W_SITE = float(os.environ.get("MUSAFIR_W_SITE", "0.05"))  # how many other sites link to the result's site
# The cross-encoder's scores bunch up near 1.0 on a big index; the first-stage agreement breaks those ties.
W_RETRIEVAL = float(os.environ.get("MUSAFIR_W_RETRIEVAL", "0.05"))  # tuned on the dev split only
W_RRF_PAGERANK = float(os.environ.get("MUSAFIR_W_RRF_PAGERANK", "0.005"))  # RRF scores are ~0.01-0.03
THIN_PAGE_WORDS, THIN_PAGE_PENALTY = 50, 0.8
# Tabs. "news" means these sites; fresher stories rank higher there.
NEWS_SITES = {"bbc.com", "aljazeera.com", "thehindu.com", "indianexpress.com", "timesofindia.indiatimes.com",
              "hindustantimes.com", "theverge.com", "arstechnica.com", "techcrunch.com", "wired.com", "skysports.com",
              "espn.com", "billboard.com", "rollingstone.com", "nme.com", "pitchfork.com", "scientificamerican.com",
              "abcnews.go.com", "cbsnews.com", "dw.com", "euronews.com", "independent.co.uk", "indiatoday.in",
              "livemint.com", "economictimes.indiatimes.com", "theprint.in", "scroll.in", "deccanherald.com",
              "variety.com", "hollywoodreporter.com", "deadline.com", "bollywoodhungama.com", "filmfare.com",
              "pinkvilla.com", "cinemaexpress.com"}
W_NEWS_FRESHNESS = 0.3
MIN_TAB_RELEVANCE = 0.1  # images, videos and news hide pages the cross-encoder scores below this
KINDS = ("all", "images", "videos", "news")
REFRESH_SECONDS = float(os.environ.get("MUSAFIR_REFRESH_SECONDS", "300"))  # how often search picks up new pages

# REST API
RATE_LIMIT_PER_MINUTE = int(os.environ.get("MUSAFIR_RATE_LIMIT_PER_MINUTE", "60"))  # per API key
# Reverse proxies (IPs or ranges) whose X-Forwarded-For is believed
TRUSTED_PROXIES = os.environ.get("MUSAFIR_TRUSTED_PROXIES", "127.0.0.1")
CORS_ORIGINS = os.environ.get("MUSAFIR_CORS_ORIGINS", "*").split(",")  # websites allowed to call the API

# Website
KEY_SIGNUPS_PER_HOUR = int(os.environ.get("MUSAFIR_KEY_SIGNUPS_PER_HOUR", "3"))  # free API keys per visitor IP
UI_RATE_LIMIT_PER_MINUTE = int(os.environ.get("MUSAFIR_UI_RATE_LIMIT_PER_MINUTE", "30"))  # per visitor IP

# Operations
LOG_LEVEL = os.environ.get("MUSAFIR_LOG_LEVEL", "INFO")  # DEBUG shows every fetched URL


def read_seeds(path=None):
    """Return the seed URLs, skipping blank lines and # comments."""
    lines = Path(path or SEEDS_FILE).read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]
