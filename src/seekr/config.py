"""All settings in one place. Override any of them with an environment variable."""
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

DB_PATH = Path(os.environ.get("SEEKR_DB", "data/seekr.db"))
SEEDS_FILE = Path(os.environ.get("SEEKR_SEEDS", PACKAGE / "crawl" / "seeds.txt"))
CONTACT = os.environ.get("SEEKR_CONTACT", "")  # e.g. "Your Name; you@example.com". Some sites (Wikipedia) require it
USER_AGENT = os.environ.get("SEEKR_USER_AGENT", f"SeekrBot/0.1 ({CONTACT})" if CONTACT else "SeekrBot/0.1")
HOST = os.environ.get("SEEKR_HOST", "127.0.0.1")
PORT = int(os.environ.get("SEEKR_PORT", "8000"))

# Crawler
MAX_DEPTH = int(os.environ.get("SEEKR_MAX_DEPTH", "3"))
MAX_PAGES_PER_DOMAIN = int(os.environ.get("SEEKR_MAX_PAGES_PER_DOMAIN", "300"))
LIVE_INTERVAL = float(os.environ.get("SEEKR_LIVE_INTERVAL", "600"))  # seconds between index runs in `live`
CRAWL_ROUND = float(os.environ.get("SEEKR_CRAWL_ROUND", "1800"))  # `live` restarts the crawl this often, with new sites
DISCOVER_MIN_LINKS = int(os.environ.get("SEEKR_DISCOVER_MIN_LINKS", "3"))  # other sites that must link to a new one
DISCOVER_PER_ROUND = int(os.environ.get("SEEKR_DISCOVER_PER_ROUND", "20"))  # sites checked per `discover`
CRAWL_DELAY = float(os.environ.get("SEEKR_CRAWL_DELAY", "1.0"))  # seconds between requests to one host
REQUEST_TIMEOUT = float(os.environ.get("SEEKR_REQUEST_TIMEOUT", "15"))
MAX_PAGE_BYTES = int(os.environ.get("SEEKR_MAX_PAGE_BYTES", "5000000"))  # long Wikipedia articles are over 2 MB
RETRIES = int(os.environ.get("SEEKR_RETRIES", "2"))

# Extraction
CHUNK_WORDS = int(os.environ.get("SEEKR_CHUNK_WORDS", "300"))
CHUNK_OVERLAP = int(os.environ.get("SEEKR_CHUNK_OVERLAP", "50"))

# Embeddings (runs on the GPU when there is one)
EMBED_MODEL = os.environ.get("SEEKR_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_BATCH = int(os.environ.get("SEEKR_EMBED_BATCH", "64"))
# CPU threads for model math. Laptop CPUs mix fast and slow cores; using every core makes the fast ones wait
# (measured on a 16-core Core Ultra: 12 threads rerank in 0.47 s, 16 threads in 2.2 s). Small servers use all cores.
_CORES = os.cpu_count() or 1
CPU_THREADS = int(os.environ.get("SEEKR_CPU_THREADS", _CORES if _CORES <= 8 else _CORES * 3 // 4))
DEVICE = os.environ.get("SEEKR_DEVICE", "")  # "", "cuda", "xpu" (Intel Arc), "mps" or "cpu"; "" picks the best one

# Search and relevance scoring
CANDIDATES = int(os.environ.get("SEEKR_CANDIDATES", "100"))  # from each of BM25 and vectors
RERANK_TOP = int(os.environ.get("SEEKR_RERANK_TOP", "30"))  # pages the cross-encoder reads per query
# MiniLM beat BAAI/bge-reranker-base on our eval (MRR 0.733 vs 0.648) and is 3x faster; try either.
RERANK_MODEL = os.environ.get("SEEKR_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_MAX_TOKENS = int(os.environ.get("SEEKR_RERANK_MAX_TOKENS", "384"))
# Tuned on evals/queries.jsonl. Freshness is 0: docs show "last updated today", so dates mislead.
W_RELEVANCE, W_PAGERANK, W_FRESHNESS, W_EXACT = 0.90, 0.05, 0.0, 0.05
W_SITE = float(os.environ.get("SEEKR_W_SITE", "0.05"))  # how many other sites link to the result's site
# The cross-encoder's scores bunch up near 1.0 on a big index; the first-stage agreement breaks those ties.
W_RETRIEVAL = float(os.environ.get("SEEKR_W_RETRIEVAL", "0.05"))  # tuned on the dev split only
W_RRF_PAGERANK = float(os.environ.get("SEEKR_W_RRF_PAGERANK", "0.005"))  # RRF scores are ~0.01-0.03
THIN_PAGE_WORDS, THIN_PAGE_PENALTY = 50, 0.8
REFRESH_SECONDS = float(os.environ.get("SEEKR_REFRESH_SECONDS", "300"))  # how often search picks up new pages

# REST API
RATE_LIMIT_PER_MINUTE = int(os.environ.get("SEEKR_RATE_LIMIT_PER_MINUTE", "60"))  # per API key
TRUSTED_PROXIES = os.environ.get("SEEKR_TRUSTED_PROXIES", "127.0.0.1")  # reverse proxy IPs ("*" inside Docker)
CORS_ORIGINS = os.environ.get("SEEKR_CORS_ORIGINS", "*").split(",")  # websites allowed to call the API

# Website
KEY_SIGNUPS_PER_HOUR = int(os.environ.get("SEEKR_KEY_SIGNUPS_PER_HOUR", "3"))  # free API keys per visitor IP
UI_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SEEKR_UI_RATE_LIMIT_PER_MINUTE", "30"))  # per visitor IP

# Operations
LOG_LEVEL = os.environ.get("SEEKR_LOG_LEVEL", "INFO")  # DEBUG shows every fetched URL


def read_seeds(path=None):
    """Return the seed URLs, skipping blank lines and # comments."""
    lines = Path(path or SEEDS_FILE).read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]
