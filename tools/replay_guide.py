"""Rebuild the project from guide.html alone, one chapter at a time, and run each stage's tests.

check_guide.py only compares the LAST listing of each file. This catches the other mistake: an earlier
chapter showing a version of a file that doesn't work at that point in the guide.
Usage: python tools/replay_guide.py   (builds into a temporary folder; your project is not touched)
"""
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ChapterListings(HTMLParser):
    """Collects (chapter number, path, code) for every <pre data-file="..."> block, in page order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.listings, self.chapter, self.path, self.parts = [], None, None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h2":  # chapter headings are <h2 id="ch3">; the map and the appendix don't count
            self.chapter = int(attrs["id"][2:]) if re.fullmatch(r"ch\d+", attrs.get("id", "")) else None
        if tag == "pre" and "data-file" in attrs:
            self.path, self.parts = attrs["data-file"], []

    def handle_endtag(self, tag):
        if tag == "pre" and self.path:
            self.listings.append((self.chapter, self.path, "".join(self.parts)))
            self.path = None

    def handle_data(self, data):
        if self.path:
            self.parts.append(data)


def main():
    parser = ChapterListings()
    parser.feed((ROOT / "guide.html").read_text())
    chapters = sorted({chapter for chapter, _, _ in parser.listings if chapter})
    failed = []
    with tempfile.TemporaryDirectory() as work:
        for chapter in chapters:
            folder = Path(work) / f"ch{chapter}"
            for listed_in, path, code in parser.listings:
                if listed_in and listed_in <= chapter:  # later listings of a file replace earlier ones
                    (folder / path).parent.mkdir(parents=True, exist_ok=True)
                    (folder / path).write_text(code.strip("\n") + "\n")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                    cwd=folder, capture_output=True, text=True)
            summary = (result.stdout.strip().splitlines() or ["no output"])[-1]
            print(f"chapter {chapter}: {'ok    ' if result.returncode == 0 else 'FAILED'} {summary}")
            if result.returncode != 0:
                failed.append(chapter)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
