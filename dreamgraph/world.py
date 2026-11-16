"""Competing multi-hop ownership chains.

Each company has three paths to a person: a 3-hop chain that is usually the
true owner, and two 2-hop chains that are not. Edge labels are the vendor.
Drift swaps wikidata and scraper labels; the people stay put. There is no
cross edge and no shortcut stage.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from dreamgraph.config import (
    CHAIN_P_TRUE,
    CHAIN_SOURCES,
    DRIFT_MIN_REL,
    HELD_OUT,
    TRAIN_REL_COUNT,
)


@dataclass
class Edge:
    src: int
    dst: int
    source: str
    rel_id: int
    hop: int

    def as_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "source": self.source,
            "rel_id": self.rel_id,
            "hop": self.hop,
        }


@dataclass
class Chain:
    name: str
    rel_id: int
    edge_indexes: list[int]
    person: int

    def as_dict(self, edges: list[Edge]) -> dict:
        return {
            "name": self.name,
            "rel_id": self.rel_id,
            "sources": [edges[index].source for index in self.edge_indexes],
            "person": self.person,
            "nodes": _nodes_of(edges, self.edge_indexes),
        }


def _nodes_of(edges: list[Edge], indexes: list[int]) -> list[int]:
    nodes = [edges[indexes[0]].src]
    nodes.extend(edges[index].dst for index in indexes)
    return nodes


@dataclass
class World:
    seed: int
    edges: list[Edge]
    chains: dict[int, list[Chain]]
    leaf: dict[int, int]
    gold: dict[int, int]
    persons: set[int]
    names: dict[int, str]
    kinds: dict[int, str]
    train_rels: list[int]
    heldout_rels: list[int]
    drifted: bool = False
    birth_source: dict[int, str] = field(default_factory=dict)
    # Poison is off unless a scenario sets it. It flips reviewer feedback on
    # train relations only. Endpoints and held-out gold do not move.
    poison_source: str | None = None
    poison_false_friend: str | None = None
    projects: dict[int, str] = field(default_factory=dict)

    def edges_as_dicts(self) -> list[dict]:
        return [edge.as_dict() for edge in self.edges]

    def chains_as_dicts(self) -> dict[int, list[dict]]:
        return {
            rel_id: [chain.as_dict(self.edges) for chain in chains]
            for rel_id, chains in self.chains.items()
        }


def train_relation_ids() -> list[int]:
    return list(range(TRAIN_REL_COUNT))


def heldout_relation_ids() -> list[int]:
    return list(range(1000, 1000 + HELD_OUT))


_GIVEN = (
    "Avery",
    "Blake",
    "Cameron",
    "Devon",
    "Ellis",
    "Finley",
    "Gray",
    "Harper",
    "Indigo",
    "Jordan",
    "Kai",
    "Logan",
    "Marlow",
    "Noor",
    "Oakley",
    "Parker",
)


def _base(seed: int, rel_id: int) -> int:
    return 100_000_000 + seed * 2_000_000 + rel_id * 40


def generate_world(seed: int) -> World:
    rng = random.Random(seed)
    edges: list[Edge] = []
    chains: dict[int, list[Chain]] = {}
    leaf: dict[int, int] = {}
    gold: dict[int, int] = {}
    persons: set[int] = set()
    names: dict[int, str] = {}
    kinds: dict[int, str] = {}
    birth: dict[int, str] = {}
    train = train_relation_ids()
    heldout = heldout_relation_ids()

    for rel_id in train + heldout:
        base = _base(seed, rel_id)
        company = base + 1
        true_person = base + 2
        leaf[rel_id] = company
        gold[rel_id] = true_person
        names[company] = f"Northwind {rel_id}"
        kinds[company] = "company"
        names[true_person] = f"{_GIVEN[rel_id % len(_GIVEN)]} Holt"
        kinds[true_person] = "person"
        persons.add(true_person)
        chains[rel_id] = []
        cursor = 3
        for name, sources in CHAIN_SOURCES.items():
            correct = rng.random() < CHAIN_P_TRUE[name]
            person = true_person if correct else base + cursor
            cursor += 1
            if person != true_person:
                names[person] = f"{name} decoy {rel_id}"
                kinds[person] = "person"
                persons.add(person)
            mids = [base + cursor + offset for offset in range(len(sources) - 1)]
            cursor += len(sources)
            for mid in mids:
                names[mid] = f"{name} claim {rel_id}"
                kinds[mid] = "claim"
            nodes = [company, *mids, person]
            indexes = []
            for hop, (src, dst, source) in enumerate(zip(nodes, nodes[1:], sources)):
                indexes.append(len(edges))
                edges.append(Edge(src, dst, source, rel_id, hop))
                birth[len(edges) - 1] = source
            chains[rel_id].append(Chain(name, rel_id, indexes, person))

    return World(
        seed=seed,
        edges=edges,
        chains=chains,
        leaf=leaf,
        gold=gold,
        persons=persons,
        names=names,
        kinds=kinds,
        train_rels=train,
        heldout_rels=heldout,
        birth_source=birth,
    )


def apply_drift(world: World, min_rel: int = DRIFT_MIN_REL) -> dict[str, int]:
    """Swap wikidata and scraper labels on relations at or above ``min_rel``."""

    if world.drifted:
        return {"wikidata_to_scraper": 0, "scraper_to_wikidata": 0, "already": 1}
    wiki = scraper = 0
    for edge in world.edges:
        if edge.rel_id < min_rel:
            continue
        if edge.source == "wikidata":
            edge.source = "scraper"
            wiki += 1
        elif edge.source == "scraper":
            edge.source = "wikidata"
            scraper += 1
    world.drifted = True
    return {"wikidata_to_scraper": wiki, "scraper_to_wikidata": scraper, "already": 0}


def world_sources(world: World) -> tuple[str, ...]:
    """Source labels in first-seen order. Empty worlds fall back to the defaults."""

    found: list[str] = []
    seen: set[str] = set()
    for edge in world.edges:
        if edge.source not in seen:
            seen.add(edge.source)
            found.append(edge.source)
    return tuple(found)


def edge_feedback(world: World, rel_id: int) -> list[tuple[str, bool]]:
    """Current label of each edge, and whether its chain names the true owner.

    When ``poison_source`` is set, train relations report that source as wrong
    and ``poison_false_friend`` as right. Held-out relations stay factual.
    The edges themselves are not rewritten.
    """

    gold = world.gold[rel_id]
    poisoned = world.poison_source is not None and rel_id in world.train_rels
    rows = []
    for chain in world.chains[rel_id]:
        correct = chain.person == gold
        for index in chain.edge_indexes:
            source = world.edges[index].source
            bit = correct
            if poisoned and source == world.poison_source:
                bit = False
            elif poisoned and world.poison_false_friend and source == world.poison_false_friend:
                bit = True
            rows.append((source, bit))
    return rows


def chain_hops(world: World, rel_id: int, name: str) -> int:
    chain = next(item for item in world.chains[rel_id] if item.name == name)
    return len(chain.edge_indexes)
