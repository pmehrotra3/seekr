"""URL helpers: clean up links and decide which ones we are allowed to crawl."""
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src"}
SKIP_EXTENSIONS = (
    ".pdf", ".zip", ".gz", ".tar", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".ico", ".css", ".js", ".json", ".xml", ".txt", ".mp3", ".mp4", ".epub",
    # downloads: the crawler would only learn they aren't HTML after a request and a crawl delay
    ".xz", ".bz2", ".tgz", ".7z", ".rar", ".asc", ".sig", ".sha256", ".exe", ".msi", ".dmg", ".pkg",
    ".deb", ".rpm", ".whl", ".iso", ".apk", ".tar.zst", ".zst", ".csv", ".woff", ".woff2", ".avi", ".mov", ".webm",
)


def normalize_url(href, base=""):
    """Make a link absolute and canonical, or return None if it isn't a web link."""
    try:
        parts = urlsplit(urljoin(base, href.strip()))
    except ValueError:  # malformed links like "http://[oops/" exist on real pages
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not key.startswith("utm_") and key not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def build_scopes(seeds):
    """Each seed allows its host plus the folder it lives in, e.g. docs.python.org + /3/."""
    scopes = []
    for seed in seeds:
        parts = urlsplit(normalize_url(seed))
        folder = parts.path[: parts.path.rfind("/") + 1]
        scopes.append((parts.netloc, folder))
    return scopes


def in_scope(url, scopes):
    parts = urlsplit(url)
    if parts.path.lower().endswith(SKIP_EXTENSIONS):
        return False
    return any(parts.netloc == host and parts.path.startswith(folder) for host, folder in scopes)
