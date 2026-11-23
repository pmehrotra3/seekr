"""Check that every full-file code block in guide.html matches the real file.

A block written as <pre data-file="seekr/config.py"> is a full-file listing.
If a file is shown more than once, the LAST listing must match the file on disk.
"""
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FileBlocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = {}
        self.path = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "pre" and "data-file" in attrs:
            self.path, self.parts = attrs["data-file"], []

    def handle_endtag(self, tag):
        if tag == "pre" and self.path:
            self.blocks[self.path] = "".join(self.parts)
            self.path = None

    def handle_data(self, data):
        if self.path:
            self.parts.append(data)


def main():
    parser = FileBlocks()
    parser.feed((ROOT / "guide.html").read_text())
    problems = []
    for path, shown in parser.blocks.items():
        real = ROOT / path
        if not real.exists():
            problems.append(f"{path}: shown in guide but missing on disk")
        elif real.read_text().strip("\n") != shown.strip("\n"):
            problems.append(f"{path}: guide listing differs from the file on disk")
    for problem in problems:
        print("MISMATCH", problem)
    print(f"checked {len(parser.blocks)} files, {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
