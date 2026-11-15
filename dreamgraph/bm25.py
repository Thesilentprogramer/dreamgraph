"""BM25 over the vendor labels on each competing chain.

The query prefers the literal word wikidata. It does not read reviewer
feedback, so a label swap moves which chain looks authoritative.
"""

from __future__ import annotations

import math
from collections import Counter

from dreamgraph.config import BM25_QUERY
from dreamgraph.world import World


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
        length = len(doc) or 1
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


def rank_chain(world: World, rel_id: int) -> tuple[int, tuple[str, ...]]:
    """Return (person, source labels) of the highest-scoring chain."""

    documents = []
    chains = []
    for chain in world.chains[rel_id]:
        sources = tuple(world.edges[index].source for index in chain.edge_indexes)
        documents.append([*sources, "ownership", "evidence"])
        chains.append((chain.person, sources))
    scores = _scores(BM25_QUERY, documents)
    best = max(range(len(chains)), key=lambda index: (scores[index], -chains[index][0]))
    return chains[best]
