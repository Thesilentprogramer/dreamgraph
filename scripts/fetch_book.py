"""Download the Book truth-discovery slice and write the cached claims.

The upstream files are the research distribution at
https://lunadong.com/fusionDataSets.htm (Yin, Han, and Yu, TKDE 2008;
Dong, Berti-Equille, and Srivastava, VLDB 2009). This script checks the
sha256 of ``book.zip`` and ``book_golden.txt``, keeps listings from three
booksellers on the gold ISBNs, and writes ``data/book/claims.jsonl``.

The committed jsonl is the cache the benchmark loads. Re-run this script
when refreshing it. The three sellers are fixed by coverage on the gold
set (each lists many of the 100 covered books), not by a search over
accuracy.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "book" / "claims.jsonl"

BOOK_ZIP = "https://lunadong.com/datasets/book.zip"
GOLD_TXT = "https://lunadong.com/datasets/book_golden.txt"
ZIP_SHA256 = "2967800b3bf99eebd25807b8f28dea77c64d93a574806fe82d76e548642c6e65"
GOLD_SHA256 = "7b05f0b1b96bb0d264b4e4ce2ce9175225fb877e02a93e984233b20643b84fcd"

# Fixed before looking at which split is held out. Alphabetical order is
# also the node-id order the unweighted tie-break will prefer.
SOURCES = ("Revaluation Books", "The Book Depository", "textbooksNow")


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def build_rows(book_zip: bytes, gold_txt: bytes) -> list[dict]:
    if _sha256(book_zip) != ZIP_SHA256:
        raise SystemExit("book.zip checksum mismatch")
    if _sha256(gold_txt) != GOLD_SHA256:
        raise SystemExit("book_golden.txt checksum mismatch")
    gold: dict[str, str] = {}
    for line in gold_txt.decode("latin1").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        isbn, authors = line.split("\t", 1)
        gold[isbn.strip()] = authors.strip()
    claims: dict[str, dict[str, dict]] = defaultdict(dict)
    with zipfile.ZipFile(BytesIO(book_zip)) as archive:
        text = archive.read("book.txt").decode("latin1")
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        source, isbn, title, authors = parts[0], parts[1].strip(), parts[2].strip(), parts[3].strip()
        if isbn not in gold or source not in SOURCES:
            continue
        if not authors or authors.lower() in {"not available", "n/a", "none"}:
            continue
        claims[isbn].setdefault(
            source,
            {"isbn": isbn, "title": title, "source": source, "authors": authors, "gold": gold[isbn]},
        )
    rows = []
    for isbn in sorted(claims):
        if len(claims[isbn]) < 2:
            continue
        for source in SOURCES:
            row = claims[isbn].get(source)
            if row:
                rows.append(row)
    return rows


def main() -> None:
    print("downloading", BOOK_ZIP, flush=True)
    book_zip = _get(BOOK_ZIP)
    gold_txt = _get(GOLD_TXT)
    rows = build_rows(book_zip, gold_txt)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    OUT.write_text(payload)
    digest = _sha256(payload.encode())
    print(f"wrote {OUT} rows={len(rows)} sha256={digest}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(exc, file=sys.stderr)
        raise
