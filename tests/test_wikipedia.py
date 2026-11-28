import bz2

from musafir import db
from musafir.index import wikipedia

ACTOR = """{{Short description|Indian actor}}
{{Infobox person
| name = Shah Rukh Khan
| image = Shah Rukh Khan in 2023.jpg
| caption = Khan in 2023
| birth_date = {{birth date and age|1965|11|2|df=y}}
| occupation = {{hlist|Actor|film producer}}
| years_active = 1988–present
}}
'''Shah Rukh Khan''' ({{lang|hi|शाहरुख़ ख़ान}}; born 2 November 1965) is an Indian [[actor]] and film producer.<ref>x</ref>
He is known as the "[[King Khan]]" of [[Bollywood]] and has appeared in more than 90 films.

== Early life ==
Khan was born in [[New Delhi]]. He studied at [[Hansraj College]] and later moved to [[Mumbai]] to act in films.

== References ==
{{reflist}}
"""
DISAMBIGUATION = "{{disambiguation}} '''Khan''' may refer to many people. " + "word " * 50


def page(title, ns, text, extra=""):
    text = text.replace("<", "&lt;")
    return f"<page><title>{title}</title><ns>{ns}</ns>{extra}<revision><text>{text}</text></revision></page>"


DUMP = ('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        + page("Shah Rukh Khan", 0, ACTOR)
        + page("SRK", 0, "#REDIRECT [[Shah Rukh Khan]]", '<redirect title="Shah Rukh Khan" />')
        + page("Talk:Shah Rukh Khan", 1, ACTOR)
        + page("Khan (disambiguation)", 0, DISAMBIGUATION)
        + "</mediawiki>")


def test_article_becomes_a_document_with_its_facts_and_picture():
    doc = wikipedia.to_document(("Shah Rukh Khan", ACTOR))
    assert doc["text"].startswith("Shah Rukh Khan (शाहरुख़ ख़ान; born 2 November 1965) is an Indian actor")
    assert "Birth date: 2 November 1965." in doc["text"] and "Occupation: Actor, film producer." in doc["text"]
    assert doc["text"].index("Occupation") < doc["text"].index("Early life")  # facts sit next to the opening
    assert "Hansraj College" in doc["text"] and "reflist" not in doc["text"] and "References" not in doc["text"]
    assert doc["image"] == "https://en.wikipedia.org/wiki/Special:FilePath/Shah_Rukh_Khan_in_2023.jpg?width=400"
    assert doc["description"].startswith("Shah Rukh Khan (") and "Caption" not in doc["text"]


def test_dump_import_skips_redirects_talk_pages_and_disambiguation(tmp_path):
    path = tmp_path / "dump.xml.bz2"
    path.write_bytes(bz2.compress(DUMP.encode()))
    assert [title for title, _ in wikipedia.articles(path)] == ["Shah Rukh Khan", "Khan (disambiguation)"]
    conn = db.connect(tmp_path / "t.db")
    counts = wikipedia.import_dump(conn, path)
    assert counts == {"new": 1, "duplicate": 0, "known": 0, "skipped": 1}
    assert conn.execute("SELECT url FROM documents").fetchone()[0] == "https://en.wikipedia.org/wiki/Shah_Rukh_Khan"
    assert wikipedia.import_dump(conn, path)["known"] == 1  # running it again adds nothing


def test_article_urls_match_wikipedias():
    assert wikipedia.article_url("Jawan (film)") == "https://en.wikipedia.org/wiki/Jawan_(film)"
    assert wikipedia.article_url("Beyoncé") == "https://en.wikipedia.org/wiki/Beyonc%C3%A9"


def test_each_article_is_one_chunk():
    from musafir import config
    from musafir.index import extract

    long_article = ACTOR.replace("He is known", "He is known " + "and famous " * 400)
    doc = wikipedia.to_document(("Shah Rukh Khan", long_article))
    assert len(doc["text"].split()) == config.WIKI_WORDS and len(extract.chunk_words(doc["text"])) == 1
