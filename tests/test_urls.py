from musafir.crawl.urls import build_scopes, in_scope, normalize_url


def test_normalize_makes_links_absolute_and_clean():
    base = "https://Docs.Python.org/3/library/"
    assert normalize_url("asyncio.html#top", base) == "https://docs.python.org/3/library/asyncio.html"
    assert normalize_url("https://a.com?utm_source=x&page=2") == "https://a.com/?page=2"


def test_normalize_rejects_non_web_links():
    assert normalize_url("mailto:me@example.com") is None
    assert normalize_url("javascript:void(0)") is None
    assert normalize_url("http://[oops/") is None  # Python raises "Invalid IPv6 URL" here


def test_scopes_keep_the_seed_folder():
    scopes = build_scopes(["https://docs.python.org/3/", "https://paulgraham.com/articles.html"])
    assert scopes == [("docs.python.org", "/3/"), ("paulgraham.com", "/")]
    assert in_scope("https://docs.python.org/3/library/os.html", scopes)
    assert not in_scope("https://docs.python.org/2/library/os.html", scopes)
    assert not in_scope("https://evil.com/3/", scopes)
    assert not in_scope("https://paulgraham.com/essay.pdf", scopes)
    assert not in_scope("https://paulgraham.com/node-v23.tar.xz", scopes)
    assert not in_scope("https://paulgraham.com/Python-3.8.9.tar.xz.asc", scopes)
