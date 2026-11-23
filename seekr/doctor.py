"""`python -m seekr doctor`: check that everything Seekr needs is in place, and say how to fix what isn't."""
import importlib.metadata
import shutil
import sqlite3
import sys

from seekr import config

PACKAGES = ["httpx", "trafilatura", "torch", "sentence-transformers", "numpy", "fastapi", "uvicorn"]
# table -> the command that fills it
TABLES = {"documents": "index", "chunks": "index", "chunks_fts": "index",
          "embeddings": "index", "pagerank": "rank"}


def check_python():
    ok = sys.version_info >= (3, 11)
    return ok, f"Python {sys.version.split()[0]}" + ("" if ok else " (need 3.11 or newer)")


def check_packages():
    missing = []
    for name in PACKAGES:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        return False, f"missing packages: {', '.join(missing)} (run: pip install -r requirements.txt)"
    return True, f"{len(PACKAGES)} packages installed"


def check_device():
    from seekr import embed  # imported here because it loads torch, which takes a few seconds

    device = embed.best_device()
    return True, f"compute device: {device}" + (" (no GPU found: search works, just slower)" if device == "cpu" else "")


def check_seeds():
    seeds = config.read_seeds() if config.SEEDS_FILE.exists() else []
    return bool(seeds), f"{len(seeds)} seed URLs in {config.SEEDS_FILE.name}"


def check_database():
    if not config.DB_PATH.exists():
        return False, f"no database at {config.DB_PATH} (run: python -m seekr crawl)"
    conn = sqlite3.connect(config.DB_PATH)
    counts = {}
    for table, command in TABLES.items():
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            return False, f"table {table} is missing (run: python -m seekr {command})"
        if counts[table] == 0:
            return False, f"table {table} is empty (run: python -m seekr {command})"
    if not counts["chunks"] == counts["chunks_fts"] == counts["embeddings"]:
        return False, (f"index is out of date: {counts['chunks']} chunks, {counts['chunks_fts']} keyword-indexed, "
                       f"{counts['embeddings']} embedded (run: python -m seekr index)")
    return True, ", ".join(f"{table} {count:,}" for table, count in counts.items())


def check_models():
    from huggingface_hub import CacheNotFound, scan_cache_dir

    try:
        cached = {repo.repo_id for repo in scan_cache_dir().repos}
    except CacheNotFound:  # nothing downloaded on this machine yet, e.g. a fresh Docker container
        cached = set()
    missing = [model for model in (config.EMBED_MODEL, config.RERANK_MODEL) if model not in cached]
    if missing:
        return False, (f"models not downloaded yet: {', '.join(missing)} "
                       "(run: python -m seekr index, needs internet once)")
    return True, "embedding and reranker models are cached (works offline)"


def check_disk():
    free_gb = shutil.disk_usage(config.DB_PATH.parent if config.DB_PATH.parent.exists() else ".").free / 1e9
    return free_gb > 5, f"{free_gb:.0f} GB free disk" + ("" if free_gb > 5 else " (less than 5 GB: crawls may fail)")


CHECKS = [check_python, check_packages, check_device, check_seeds, check_database, check_models, check_disk]


def run_checks():
    """Run every check, print one line each, and return True if all passed."""
    all_ok = True
    for check in CHECKS:
        try:
            ok, message = check()
        except Exception as error:  # a broken check must not hide the others
            ok, message = False, f"{check.__name__} crashed: {error}"
        print(f"{'✓' if ok else '✗'} {message}")
        all_ok &= ok
    return all_ok
