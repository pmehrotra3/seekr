from seekr import db
from seekr.index import extract

ARTICLE = """<html lang="en-US"><head><title>Ownership - The Book</title></head><body>
<nav><a href="/">Home</a> <a href="/about">About</a></nav>
<article><h1>What is ownership?¶</h1>
<p>Ownership is a set of rules that govern how a program manages memory. Every value has
an owner, and there can only be one owner at a time.</p>
<p>When the owner goes out of scope, the value is dropped and its memory is freed. This lets
the language guarantee memory safety without needing a garbage collector at runtime.</p>
</article><footer>Copyright 2026</footer></body></html>"""


def test_extract_keeps_main_text_and_drops_boilerplate():
    doc = extract.extract(ARTICLE, "https://x.com/own", "Ownership - The Book")
    assert doc["title"] == "Ownership - The Book"
    assert doc["language"] == "en-us"
    assert "only be one owner" in doc["text"]
    assert "¶" not in doc["text"]
    assert "Copyright" not in doc["text"] and "About" not in doc["text"]


def test_chunks_overlap():
    words = " ".join(f"w{i}" for i in range(25))
    chunks = extract.chunk_words(words, size=10, overlap=3)
    assert chunks[0].split()[-3:] == chunks[1].split()[:3]
    assert chunks[-1].endswith("w24")
    assert extract.chunk_words("just a few words", size=10, overlap=3) == ["just a few words"]


def test_content_hash_ignores_case_and_spacing():
    assert extract.content_hash("Hello   World") == extract.content_hash("hello world")


def test_duplicates_and_empty_pages_get_no_chunks(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    doc = extract.extract(ARTICLE, "https://x.com/a")
    assert extract.save_document(conn, "https://x.com/a", doc) == "new"
    assert extract.save_document(conn, "https://x.com/a-copy", doc) == "duplicate"
    assert extract.save_document(conn, "https://x.com/links", None) == "empty"
    assert conn.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks").fetchone()[0] == 1


def test_index_pages_is_incremental(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.save_page(conn, "https://x.com/a", "https://x.com/a", 200, "A", ARTICLE, [])
    assert extract.index_pages(conn)["new"] == 1
    assert sum(extract.index_pages(conn).values()) == 0


def test_page_image_reads_the_preview_tag():
    page = '<head><meta content="/img/a.jpg?x=1&amp;y=2" property="og:image"></head>'
    assert extract.page_image(page, "https://site.com/post") == "https://site.com/img/a.jpg?x=1&y=2"
    assert extract.page_image('<meta name="twitter:image" content="https://cdn.com/b.png">', "") == "https://cdn.com/b.png"
    assert extract.page_image('<meta property="og:image" content="http://old.com/c.jpg">', "") == ""  # not https
    assert extract.page_image("<p>no image</p>", "https://site.com/") == ""


def test_older_pages_get_their_images_filled_in(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    page = '<meta property="og:image" content="https://cdn.com/x.jpg">'
    db.save_page(conn, "https://a.com/", "https://a.com/", 200, "A", page, [])
    conn.execute("INSERT INTO documents (url, word_count) VALUES ('https://a.com/', 10)")  # indexed before images
    assert extract.add_media(conn) == 1
    assert conn.execute("SELECT image FROM documents").fetchone()[0] == "https://cdn.com/x.jpg"
    assert extract.add_media(conn) == 0


def test_databases_from_before_images_are_upgraded(tmp_path):
    import sqlite3

    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, title TEXT, description TEXT"
                ", published TEXT, language TEXT, word_count INTEGER, content_hash TEXT, duplicate_of INTEGER)")
    old.commit()
    old.close()
    columns = [row[1] for row in db.connect(tmp_path / "old.db").execute("PRAGMA table_info(documents)")]
    assert "image" in columns


def test_page_video_finds_embedded_players():
    embed = '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"></iframe>'
    assert extract.page_video(embed, "") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert extract.page_video('<iframe src="https://player.vimeo.com/video/76979871"></iframe>', "") == \
        "https://vimeo.com/76979871"
    declared = '<meta property="og:video:secure_url" content="/media/talk.mp4">'
    assert extract.page_video(declared, "https://dev.example.com/talks/1") == "https://dev.example.com/media/talk.mp4"
    assert extract.page_video('<a href="https://youtube.com/@nasa">YouTube</a>', "") == ""  # a social link
