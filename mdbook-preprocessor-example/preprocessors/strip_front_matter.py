#!/usr/bin/env python3
"""mdBook preprocessor to strip YAML front matter from Markdown files."""

import json
import re
import sys


def strip_front_matter(content: str) -> str:
    pattern = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
    return pattern.sub("", content, count=1)


def process_chapter(chapter):
    chapter["content"] = strip_front_matter(chapter["content"])
    for sub in chapter.get("sub_items", []):
        if "Chapter" in sub:
            process_chapter(sub["Chapter"])


def process_book(book):
    for section in book.get("items", []):
        if "Chapter" in section:
            process_chapter(section["Chapter"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "supports":
        sys.exit(0)

    context, book = json.load(sys.stdin)
    process_book(book)
    print(json.dumps(book))


if __name__ == "__main__":
    main()
