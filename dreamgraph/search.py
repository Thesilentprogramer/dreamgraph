"""Weighted and unweighted owner search.

The same tie break (lower path of node ids) is used for every method so an
unweighted result is reproducible and is not secretly sorted by source name.
"""

from __future__ import annotations

import heapq
import math
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


def one_hop_owner(world: World, rel_id: int, costs: dict[str, float] | None) -> Prediction:
    """Pick the chain whose first edge is cheapest, then follow that chain.

    This is a lookup on one edge. It does not sum the path and it does not
    call ``algo.SSpaths``. Ties break on the path's node-id tuple, same as
    the full search.
    """

    best_key: tuple[float, tuple[int, ...]] | None = None
    best: Prediction | None = None
    for chain in world.chains[rel_id]:
        first = world.edges[chain.edge_indexes[0]]
        step = 1.0 if costs is None else float(costs[first.source])
        if step <= 0:
            raise ValueError("edge cost must stay positive; gold edges are not pinned")
        nodes = [first.src]
        sources = []
        for index in chain.edge_indexes:
            edge = world.edges[index]
            nodes.append(edge.dst)
            sources.append(edge.source)
        path = tuple(nodes)
        key = (step, path)
        if best_key is None or key < best_key:
            best_key = key
            best = Prediction(chain.person, path, tuple(sources), step)
    if best is None:
        return Prediction(None, (world.leaf[rel_id],), (), float("inf"))
    return best


def predict_relation(world: World, rel_id: int, costs: dict[str, float] | None) -> Prediction:
    prediction = cheapest_owner(world.edges, world.leaf[rel_id], world.persons, costs)
    return prediction


def is_correct(world: World, rel_id: int, prediction: Prediction) -> bool:
    return prediction.person == world.gold[rel_id]


def combine_ends(paths: list[tuple[float, int]], *, k: int, margin: float | None) -> tuple[int | None, float]:
    """Trust-weighted vote over the paths a search actually returned.

    ``paths`` is ``(weight, end)`` pairs. Only the ``k`` cheapest are kept.
    A margin keeps a clearly cheaper path from being outvoted by a pile of
    worse ones: ends more than ``margin`` above the cheapest weight drop out.
    Ties prefer the lower end id, and a boolean end prefers ``True``.
    """

    if k <= 0:
        raise ValueError("path count must be positive")
    if not paths:
        return None, float("inf")
    ordered = sorted(paths, key=lambda item: (item[0], item[1] if not isinstance(item[1], bool) else int(item[1])))[:k]
    if margin is not None:
        limit = ordered[0][0] + margin
        kept = [item for item in ordered if item[0] <= limit + 1e-9]
        ordered = kept or ordered[:1]
    scores: dict[int, float] = {}
    for weight, end in ordered:
        scores[end] = scores.get(end, 0.0) + math.exp(-weight)

    def tie(end: int) -> float:
        if isinstance(end, bool):
            return float(end)
        return -float(end)

    chosen = max(scores, key=lambda end: (scores[end], tie(end)))
    weight = min(item[0] for item in ordered if item[1] == chosen)
    return chosen, weight


def vote_world(
    world: World,
    rel_id: int,
    book,
    *,
    k: int = 1,
    margin: float | None = None,
    conditional: bool = False,
) -> Prediction:
    """Vote the chains of one question. ``book is None`` weighs every edge at 1."""

    project = None
    if conditional and book is not None:
        project = world.projects.get(rel_id)
    paths: list[tuple[float, int]] = []
    by_end: dict[int, tuple[float, tuple[int, ...], tuple[str, ...]]] = {}
    for chain in world.chains[rel_id]:
        nodes = [world.edges[chain.edge_indexes[0]].src]
        sources = []
        weight = 0.0
        for index in chain.edge_indexes:
            edge = world.edges[index]
            step = 1.0 if book is None else book.weight(edge.source, project)
            if step <= 0:
                raise ValueError("edge cost must stay positive; gold edges are not pinned")
            weight += step
            nodes.append(edge.dst)
            sources.append(edge.source)
        path = tuple(nodes)
        paths.append((weight, chain.person))
        current = by_end.get(chain.person)
        key = (weight, path)
        if current is None or key < (current[0], current[1]):
            by_end[chain.person] = (weight, path, tuple(sources))
    chosen, weight = combine_ends(paths, k=k, margin=margin)
    if chosen is None or chosen not in by_end:
        return Prediction(None, (world.leaf[rel_id],), (), float("inf"))
    _stored, path, sources = by_end[chosen]
    return Prediction(chosen, path, sources, weight)
