"""`seekr wikipedia DUMP`: every article from Wikipedia's official dump, without crawling Wikipedia.

Download enwiki-latest-pages-articles.xml.bz2 from https://dumps.wikimedia.org/enwiki/latest/. Each article keeps
its opening paragraph, the facts in its infobox (born, occupation, starring...) and more of the article, up to
WIKI_WORDS words in all (one chunk, so 6 million articles still fit in memory for vector search), and its
infobox picture. Redirects and disambiguation pages are skipped.
"""
import bz2
import re
from concurrent.futures import ProcessPoolExecutor
from itertools import batched, islice
from urllib.parse import quote
from xml.etree.ElementTree import iterparse

import mwparserfromhell

from seekr import config
from seekr.index import extract

SKIP = re.compile(r"^(disambiguation|disambig|dab|hndis|geodis|set index|surname|given name)\b", re.I)
DATE = re.compile(r"^(birth|death|start|end|film|release|launch)[ _-]?date", re.I)
LIST = re.compile(r"^(plainlist|plain list|ubl|unbulleted list|flatlist|flat list|hlist|bulleted list|ublist)$", re.I)
MONTHS = ("January February March April May June July August September October November December").split()
BREAK = re.compile(r"<br\s*/?>", re.I)
KEEP_TEXT = re.compile(r"^(lang|lang-\w+|langx|transl|transliteration|nowrap|nobr|ill|small|sic|nihongo|zh)$", re.I)
PICTURE = re.compile(r"^(image|image_name|poster|cover|photo)$", re.I)
NOT_A_FACT = re.compile(r"image|caption|alt|signature|logo|map|coord|website|url|footnote|module|embed|size|"
                        r"upright|name$|honorific|label|width|pushpin|blank|data\d|_ref$|symbol", re.I)
EMPTY_BRACKETS = re.compile(r"\(\s*[;,]?\s*\)|\(\s*[;,]\s*")
SPACES = re.compile(r"[ \t]+")
CUT_AT = re.compile(r"^\s*(See also|References|Notes|External links|Further reading|Bibliography)\s*$", re.M | re.I)


def articles(path):
    """(title, wikitext) of every article in the dump: namespace 0 and not a redirect."""
    with bz2.open(path, "rb") as dump:
        events = iterparse(dump, events=("start", "end"))
        _, root = next(events)
        page = {}
        for event, element in events:
            if event != "end":
                continue
            tag = element.tag.rpartition("}")[2]
            if tag in ("title", "ns", "text"):
                page[tag] = element.text or ""
            elif tag == "redirect":
                page["redirect"] = True
            elif tag == "page":
                if page.get("ns") == "0" and not page.get("redirect"):
                    yield page["title"], page.get("text", "")
                page = {}
                root.clear()  # forget finished pages, or the whole dump would pile up in memory


def article_url(title):
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="/:(),'!*@$;-._~&+=")


def picture_url(value):
    name = value.split("|")[0].strip().removeprefix("File:").removeprefix("Image:").strip()
    if not re.search(r"\.(jpe?g|png|gif|webp|svg|tiff?)$", name, re.I):
        return ""
    return "https://en.wikipedia.org/wiki/Special:FilePath/" + quote(name.replace(" ", "_")) + "?width=400"


def date_text(template):
    """{{birth date and age|1965|11|2}} -> 2 November 1965"""
    parts = [str(p.value).strip() for p in template.params if not p.showkey and str(p.value).strip().isdigit()]
    if not parts:
        return ""
    year, month, day = (parts + ["", ""])[:3]
    month = MONTHS[int(month) - 1] if month and 1 <= int(month) <= 12 else ""
    return " ".join(part for part in (day, month, year) if part)


def simplify(code):
    """Turn the templates that hold real words (dates, lists, other scripts) into those words, before strip_code."""
    for template in code.filter_templates():  # innermost last, so outer templates see the replaced text
        name = str(template.name).strip().lower()
        try:
            if DATE.match(name):
                code.replace(template, date_text(template))
            elif LIST.match(name):
                items = [str(p.value).strip().lstrip("*").strip() for p in template.params if not p.showkey]
                code.replace(template, ", ".join(item for item in items if item))
            elif KEEP_TEXT.match(name) and template.params:  # e.g. {{lang|hi|Dilwale}}: keep "Dilwale"
                code.replace(template, str(template.params[-1].value))
        except ValueError:  # already replaced as part of an outer template
            continue


def plain(wikicode):
    return SPACES.sub(" ", EMPTY_BRACKETS.sub("(", wikicode.strip_code())).strip()


def to_document(item, words=None):
    """The article as a document for save_document, or None (disambiguation page, or too short)."""
    title, wikitext = item
    try:
        code = mwparserfromhell.parse(BREAK.sub(", ", wikitext))
    except Exception:  # a few pages break the parser: skip them
        return None
    templates = code.filter_templates(recursive=False)
    if any(SKIP.match(str(template.name).strip()) for template in templates):
        return None
    simplify(code)
    facts, image = [], ""
    for template in code.filter_templates(recursive=False):
        if not str(template.name).strip().lower().startswith("infobox"):
            continue
        for param in template.params:
            key = str(param.name).strip()
            if PICTURE.match(key) and not image:
                image = picture_url(str(param.value.strip_code()))
            elif not NOT_A_FACT.search(key) and not key.isdigit():
                value = plain(param.value).replace("\n", ", ").strip(" ,")
                if 0 < len(value) <= 150 and "px|" not in value and len(facts) < 15:
                    facts.append(f"{key.replace('_', ' ').capitalize()}: {value}.")
    text = CUT_AT.split(plain(code), maxsplit=1)[0].strip()
    first, _, rest = text.partition("\n\n")
    words = (first.split() + " ".join(facts).split() + rest.split())[: words or config.WIKI_WORDS]
    if len(first.split()) + len(rest.split()) < config.WIKI_MIN_WORDS:
        return None
    text = " ".join(words)  # the opening paragraph, then the infobox facts, then more of the article
    lead = first.split(". ")
    return {
        "title": title,
        "description": ". ".join(lead[:3])[:300],
        "published": "",
        "language": "en",
        "text": text,
        "image": image,
        "video": "",
    }


def import_dump(conn, path, limit=None, batch_size=2000):
    """Add the dump's articles as documents (index, rank and export them afterwards). Returns counts."""
    counts = {"new": 0, "duplicate": 0, "known": 0, "skipped": 0}
    known = {row[0] for row in conn.execute("SELECT url FROM documents WHERE url LIKE 'https://en.wikipedia.org/%'")}
    with ProcessPoolExecutor() as pool:  # parsing wikitext is the slow part: one article per core at a time
        for batch in batched(islice(articles(path), limit), batch_size):
            docs = pool.map(to_document, batch, chunksize=25)
            for (title, _), doc in zip(batch, docs, strict=True):
                url = article_url(title)
                if url in known:
                    counts["known"] += 1
                elif doc is None:
                    counts["skipped"] += 1
                else:
                    counts[extract.save_document(conn, url, doc)] += 1
            conn.commit()
            print(f"  {sum(counts.values()):,} articles: {counts}", flush=True)
    return counts
