"""Weighted and unweighted owner search.

The same tie break (lower path of node ids) is used for every method so an
unweighted result is reproducible and is not secretly sorted by source name.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from dreamgraph.world import Edge, World


@dataclass(frozen=True)
class Prediction:
    person: int | None
    path: tuple[int, ...]
    sources: tuple[str, ...]
    weight: float

def build_index(edges: list[Edge] | list[dict]) -> tuple[dict[int, list[tuple[int, str]]], dict[tuple[int, int], str]]:
    """Adjacency plus a (src, dst) → source lookup. Rebuild after a label swap."""

    adj: dict[int, list[tuple[int, str]]] = {}
    lookup: dict[tuple[int, int], str] = {}
    for edge in edges:
        if isinstance(edge, Edge):
            src, dst, source = edge.src, edge.dst, edge.source
        else:
            src, dst, source = int(edge["src"]), int(edge["dst"]), edge["source"]
        adj.setdefault(src, []).append((dst, source))
        lookup[(src, dst)] = source
    return adj, lookup


def cheapest_owner(
    edges: list[Edge] | list[dict],
    src: int,
    persons: set[int],
    costs: dict[str, float] | None,
    index: tuple[dict[int, list[tuple[int, str]]], dict[tuple[int, int], str]] | None = None,
) -> Prediction:
    """Min-cost path from ``src`` that ends on a person.

    ``costs is None`` is the unweighted graph: every edge weighs 1. Otherwise
    an edge weighs ``costs[source]``. Ties break on the path's node-id tuple.
    """

    if index is None:
        index = build_index(edges)
    adj, lookup = index
    start = (0.0, (src,))
    best: dict[int, tuple[float, tuple[int, ...]]] = {src: start}
    heap: list[tuple[float, tuple[int, ...], int]] = [(0.0, (src,), src)]
    while heap:
        weight, path, node = heapq.heappop(heap)
        if best.get(node) != (weight, path):
            continue
        for dst, source in adj.get(node, []):
            step = 1.0 if costs is None else float(costs[source])
            if step <= 0:
                raise ValueError("edge cost must stay positive; gold edges are not pinned")
            cand = (weight + step, path + (dst,))
            current = best.get(dst)
            if current is None or cand < current:
                best[dst] = cand
                heapq.heappush(heap, (cand[0], cand[1], dst))

    chosen: tuple[float, tuple[int, ...]] | None = None
    person: int | None = None
    for node, key in best.items():
        if node == src or node not in persons:
            continue
        if chosen is None or key < chosen:
            chosen = key
            person = node
    if chosen is None or person is None:
        return Prediction(None, (src,), (), float("inf"))

    sources = tuple(lookup[(chosen[1][i], chosen[1][i + 1])] for i in range(len(chosen[1]) - 1))
    return Prediction(person, chosen[1], sources, chosen[0])


def predict_relation(world: World, rel_id: int, costs: dict[str, float] | None) -> Prediction:
    prediction = cheapest_owner(world.edges, world.leaf[rel_id], world.persons, costs)
    return prediction


def is_correct(world: World, rel_id: int, prediction: Prediction) -> bool:
    return prediction.person == world.gold[rel_id]
