"""BM25 over source-label tokens. The query prefers the literal word wikidata.

This is a fixed lexical ranker. It does not read reviewer feedback, so a
label swap sends it after the renamed chain.
"""

from __future__ import annotations

import math
from collections import Counter

from dreamgraph.config import BM25_QUERY, SOURCES
from dreamgraph.world import World, source_endpoint


def _scores(query: tuple[str, ...], documents: list[list[str]], k1: float = 1.2, b: float = 0.75) -> list[float]:
    count = len(documents)
    avgdl = sum(len(doc) for doc in documents) / count
    document_frequency: Counter[str] = Counter()
    for doc in documents:
        document_frequency.update(set(doc))
    scored = []
    for doc in documents:
        term_frequency = Counter(doc)
        score = 0.0
        length = len(doc)
        for term in query:
            freq = term_frequency.get(term, 0)
            if freq == 0:
                continue
            df = document_frequency[term]
            idf = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1.0 - b + b * length / avgdl)
            score += idf * freq * (k1 + 1.0) / denom
        scored.append(score)
    return scored


def rank_sources(world: World, rel_id: int) -> str:
    documents = []
    present = []
    for source in SOURCES:
        if source_endpoint(world, rel_id, source) is None:
            continue
        present.append(source)
        documents.append([source, source, "ownership", "evidence"])
    if not present:
        raise RuntimeError(f"relation {rel_id} has no source path")
    scores = _scores(BM25_QUERY, documents)
    best = max(range(len(present)), key=lambda index: (scores[index], -index))
    return present[best]
