"""Book-seller world built from the cached gold slice.

Each ISBN is a question. Each bookseller that listed it is a two-edge chain
(book → listing → author), both edges labeled with that seller. Chains that
match the gold author list end on the gold author node. Chains that do not
end on a per-listing decoy, so nothing crosses between books.

Path length does not depend on whether the listing is right. A weighted
shortest path therefore picks the cheapest seller, and a 1-hop lookup on the
first edge picks the same seller. The synthetic ownership graph is where
those two decisions come apart.
"""

from __future__ import annotations

import json
import random
import re
import zlib
from pathlib import Path

from dreamgraph.world import Chain, Edge, World

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "data" / "book" / "claims.jsonl"

# Alphabetical. Listing node ids follow this order, so an unweighted search
# tie-breaks toward whichever of these names sorts first and is present.
BOOK_SOURCES: tuple[str, ...] = (
    "Revaluation Books",
    "The Book Depository",
    "textbooksNow",
)

# Volume prior on the cached slice (listings, not gold matches):
# Revaluation Books 55, The Book Depository 40, textbooksNow 21.
# Lower cost means more listings. Not fit on held-out labels.
BOOK_HAND_SET: dict[str, float] = {
    "Revaluation Books": 1.0,
    "The Book Depository": 2.0,
    "textbooksNow": 6.0,
}

TRAIN_BOOKS = 25
REL_BASE = 5000
TOKEN_SKIP = {"and", "the"}


def _tokens(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9']+", text.lower()) if len(tok) > 2 and tok not in TOKEN_SKIP}


def authors_match(claim: str, gold: str) -> bool:
    """Token Jaccard at least 0.5. Pre-registered match rule for this slice."""

    left, right = _tokens(gold), _tokens(claim)
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= 0.5


def load_claim_rows(path: Path = CLAIMS) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run python scripts/fetch_book.py.")
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def books_by_isbn(rows: list[dict] | None = None) -> dict[str, dict]:
    """ISBN → {title, gold, listings: {source: authors}} for books with ≥2 sellers."""

    grouped: dict[str, dict] = {}
    for row in rows if rows is not None else load_claim_rows():
        slot = grouped.setdefault(
            row["isbn"],
            {"isbn": row["isbn"], "gold": row["gold"], "titles": [], "listings": {}},
        )
        slot["titles"].append(row.get("title") or "")
        slot["listings"][row["source"]] = row["authors"]
    kept = {}
    for isbn, slot in grouped.items():
        present = [source for source in BOOK_SOURCES if source in slot["listings"]]
        if len(present) < 2:
            continue
        title = max(slot["titles"], key=len) if any(slot["titles"]) else isbn
        kept[isbn] = {
            "isbn": isbn,
            "gold": slot["gold"],
            "title": title,
            "listings": {source: slot["listings"][source] for source in present},
        }
    return kept


def source_hit_rates(books: dict[str, dict] | None = None) -> dict[str, dict]:
    """Descriptive accuracy of each seller on this slice. Not a training input."""

    books = books if books is not None else books_by_isbn()
    rates = {}
    for source in BOOK_SOURCES:
        hits = total = 0
        for book in books.values():
            claim = book["listings"].get(source)
            if claim is None:
                continue
            total += 1
            hits += int(authors_match(claim, book["gold"]))
        rates[source] = {
            "hits": hits,
            "n": total,
            "accuracy": None if total == 0 else round(hits / total, 6),
        }
    return rates


def _author_slots(isbn: str, sellers: int) -> tuple[int, list[int]]:
    """Gold and decoy slots overlap on purpose.

    A tie-break on person id must not be able to read correctness off the
    numbering. Listing ids stay in front of author ids so an unweighted path
    still breaks ties on the seller's listing node, which is the documented
    alphabetical order.
    """

    seed = zlib.crc32(isbn.encode()) & 0xFFFFFFFF
    used: set[int] = set()

    def take(key: int) -> int:
        slot = 20 + (key % 30)
        while slot in used:
            slot += 1
        used.add(slot)
        return slot

    gold_slot = take(seed)
    decoys = [take(seed + 17 * (index + 1)) for index in range(sellers)]
    return gold_slot, decoys


def _clip(text: str, limit: int = 88) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def generate_public_world(seed: int, train_books: int = TRAIN_BOOKS) -> World:
    books = books_by_isbn()
    isbns = sorted(books)
    if len(isbns) <= train_books + 5:
        raise RuntimeError(f"book slice has {len(isbns)} questions; need a train and a held-out set")
    order = list(isbns)
    random.Random(seed).shuffle(order)
    train_isbns = order[:train_books]
    held_isbns = order[train_books:]

    edges: list[Edge] = []
    chains: dict[int, list[Chain]] = {}
    leaf: dict[int, int] = {}
    gold: dict[int, int] = {}
    persons: set[int] = set()
    names: dict[int, str] = {}
    kinds: dict[int, str] = {}
    train_rels: list[int] = []
    held_rels: list[int] = []

    def add_book(isbn: str, rel_id: int) -> None:
        book = books[isbn]
        base = 800_000_000 + (rel_id - REL_BASE) * 80
        book_id = base + 1
        gold_slot, decoy_slots = _author_slots(isbn, len(BOOK_SOURCES))
        gold_author = base + gold_slot
        leaf[rel_id] = book_id
        gold[rel_id] = gold_author
        names[book_id] = _clip(f"{book['title']} ({isbn})")
        kinds[book_id] = "book"
        names[gold_author] = _clip(book["gold"])
        kinds[gold_author] = "author"
        persons.add(gold_author)
        chains[rel_id] = []
        for slot, source in enumerate(BOOK_SOURCES):
            claim = book["listings"].get(source)
            if claim is None:
                continue
            listing = base + 2 + slot
            match = authors_match(claim, book["gold"])
            author = gold_author
            if not match:
                author = base + decoy_slots[slot]
                names[author] = _clip(claim)
                kinds[author] = "author"
                persons.add(author)
            names[listing] = source
            kinds[listing] = "listing"
            first = len(edges)
            edges.append(Edge(book_id, listing, source, rel_id, 0))
            edges.append(Edge(listing, author, source, rel_id, 1))
            chains[rel_id].append(Chain(source, rel_id, [first, first + 1], author))

    for offset, isbn in enumerate(train_isbns):
        rel_id = REL_BASE + offset
        train_rels.append(rel_id)
        add_book(isbn, rel_id)
    for offset, isbn in enumerate(held_isbns):
        rel_id = REL_BASE + train_books + offset
        held_rels.append(rel_id)
        add_book(isbn, rel_id)

    return World(
        seed=seed,
        edges=edges,
        chains=chains,
        leaf=leaf,
        gold=gold,
        persons=persons,
        names=names,
        kinds=kinds,
        train_rels=train_rels,
        heldout_rels=held_rels,
    )
