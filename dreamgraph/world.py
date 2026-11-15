"""Synthetic multi-vendor ownership gadgets.

Each relation is three two-hop chains that share a company and otherwise do
not touch. There is no cross edge and no shortcut generator. Drift swaps the
wikidata and scraper labels; the people at the ends of the chains stay put.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from dreamgraph.config import DRIFT_MIN_REL, HELD_OUT, P_CORRECT, SOURCES, TRAIN_REL_COUNT


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
class World:
    seed: int
    edges: list[Edge]
    leaf: dict[int, int]
    gold: dict[int, int]
    persons: set[int]
    names: dict[int, str]
    kinds: dict[int, str]
    claim_of: dict[int, str]
    train_rels: list[int]
    heldout_rels: list[int]
    drifted: bool = False
    # Physical chain identity, stable across a label swap. Keyed by (rel, source_at_birth).
    birth_source: dict[tuple[int, int, int], str] = field(default_factory=dict)

    def edges_as_dicts(self) -> list[dict]:
        return [edge.as_dict() for edge in self.edges]


def train_relation_ids() -> list[int]:
    return list(range(TRAIN_REL_COUNT))


def heldout_relation_ids() -> list[int]:
    # 1000 and up, so every held-out relation is past the drift threshold.
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


def _person_name(rel_id: int, decoy: str | None) -> str:
    given = _GIVEN[rel_id % len(_GIVEN)]
    if decoy is None:
        return f"{given} Holt"
    return f"{decoy.title()} decoy {rel_id}"


def generate_world(seed: int) -> World:
    rng = random.Random(seed)
    edges: list[Edge] = []
    leaf: dict[int, int] = {}
    gold: dict[int, int] = {}
    persons: set[int] = set()
    names: dict[int, str] = {}
    kinds: dict[int, str] = {}
    claim_of: dict[int, str] = {}
    birth: dict[tuple[int, int, int], str] = {}
    train = train_relation_ids()
    heldout = heldout_relation_ids()

    for rel_id in train + heldout:
        base = 10_000_000 + rel_id * 20
        company = base + 1
        slots = [2, 3, 4]
        rng.shuffle(slots)
        claim_ids = {source: base + slots[index] for index, source in enumerate(SOURCES)}
        true_person = base + 5
        decoy = {source: base + 6 + index for index, source in enumerate(SOURCES)}

        leaf[rel_id] = company
        gold[rel_id] = true_person
        names[company] = f"Northwind {rel_id}"
        kinds[company] = "company"
        names[true_person] = _person_name(rel_id, None)
        kinds[true_person] = "person"
        persons.add(true_person)

        for source in SOURCES:
            claim = claim_ids[source]
            correct = rng.random() < P_CORRECT[source]
            person = true_person if correct else decoy[source]
            names[claim] = f"{source} claim {rel_id}"
            kinds[claim] = "claim"
            claim_of[claim] = source
            if person != true_person:
                names[person] = _person_name(rel_id, source)
                kinds[person] = "person"
                persons.add(person)
            pair = (
                Edge(company, claim, source, rel_id, 0),
                Edge(claim, person, source, rel_id, 1),
            )
            for edge in pair:
                edges.append(edge)
                birth[(edge.src, edge.dst, edge.hop)] = source

    return World(
        seed=seed,
        edges=edges,
        leaf=leaf,
        gold=gold,
        persons=persons,
        names=names,
        kinds=kinds,
        claim_of=claim_of,
        train_rels=train,
        heldout_rels=heldout,
        birth_source=birth,
    )


def apply_drift(world: World, min_rel: int = DRIFT_MIN_REL) -> dict[str, int]:
    """Swap wikidata and scraper labels on relations at or above ``min_rel``.

    Registry edges and relations below the cut are left alone. A second call
    is a no-op so a restarted process can ask for drift safely.
    """

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
    for claim_id, source in list(world.claim_of.items()):
        # Claims display the label currently on their outgoing edge.
        outgoing = next((edge for edge in world.edges if edge.src == claim_id), None)
        if outgoing is not None:
            world.claim_of[claim_id] = outgoing.source
            world.names[claim_id] = f"{outgoing.source} claim {outgoing.rel_id}"
    world.drifted = True
    return {"wikidata_to_scraper": wiki, "scraper_to_wikidata": scraper, "already": 0}


def source_endpoint(world: World, rel_id: int, source: str) -> int | None:
    """Walk the two hops currently wearing ``source`` and return the person."""

    company = world.leaf[rel_id]
    claim = next(
        (
            edge.dst
            for edge in world.edges
            if edge.rel_id == rel_id and edge.src == company and edge.source == source
        ),
        None,
    )
    if claim is None:
        return None
    person = next(
        (
            edge.dst
            for edge in world.edges
            if edge.rel_id == rel_id and edge.src == claim and edge.source == source
        ),
        None,
    )
    return person


def source_correct(world: World, rel_id: int, source: str) -> bool:
    person = source_endpoint(world, rel_id, source)
    return person is not None and person == world.gold[rel_id]
