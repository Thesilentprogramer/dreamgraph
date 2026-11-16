"""Vulnerability world: is this upstream tag affected, according to which feed?

Each question is one CVE and one tag. Each feed that casts a verdict is a
two-edge chain, question → claim → affected or not-affected. Both edges carry
that feed's learned cost, so a weighted path search picks the cheapest feed.
An ``nvd_mirror`` chain copies NVD and then flips the verdict. It is a modeled
aggregator that republishes a bad NVD range, not a feed in the cache.
"""

from __future__ import annotations

import json
import random
import zlib
from collections import defaultdict
from pathlib import Path

from dreamgraph.world import Chain, Edge, World

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "data" / "vuln" / "claims.jsonl"

REL_BASE = 8000
TRAIN_QUESTIONS = 500
MIRROR = "nvd_mirror"


def load_questions(path: Path = CLAIMS) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Run python scripts/fetch_vuln.py.")
    grouped: dict[tuple[str, str], dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["cve"], row["version"])
        slot = grouped.setdefault(
            key,
            {
                "cve": row["cve"],
                "repo": row["repo"],
                "version": row["version"],
                "gold": bool(row["gold"]),
                "modified": row.get("modified") or "",
                "votes": {},
            },
        )
        slot["votes"][row["source"]] = bool(row["affected"])
        if row.get("modified") and row["modified"] > slot["modified"]:
            slot["modified"] = row["modified"]
    questions = list(grouped.values())
    questions.sort(key=lambda item: (item["cve"], item["version"]))
    for item in questions:
        if "nvd" in item["votes"]:
            item["votes"][MIRROR] = not item["votes"]["nvd"]
    return questions


def source_names(questions: list[dict] | None = None) -> tuple[str, ...]:
    questions = questions if questions is not None else load_questions()
    found = []
    seen = set()
    for question in questions:
        for source in sorted(question["votes"]):
            if source not in seen:
                seen.add(source)
                found.append(source)
    return tuple(found)


def hand_set_costs(questions: list[dict] | None = None) -> dict[str, float]:
    """Volume prior. More claims, lower cost. Labels are not consulted."""

    questions = questions if questions is not None else load_questions()
    counts: dict[str, int] = defaultdict(int)
    for question in questions:
        for source in question["votes"]:
            counts[source] += 1
    ordered = sorted(counts, key=lambda source: (-counts[source], source))
    return {source: float(index + 1) for index, source in enumerate(ordered)}


def measured_accuracy(questions: list[dict] | None = None) -> dict[str, dict]:
    """Descriptive accuracy of each feed on this slice. Not a training input."""

    questions = questions if questions is not None else load_questions()
    hits: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    for question in questions:
        for source, vote in question["votes"].items():
            total[source] += 1
            hits[source] += int(vote is question["gold"])
    return {
        source: {
            "hits": hits[source],
            "n": total[source],
            "accuracy": round(hits[source] / total[source], 6),
        }
        for source in sorted(total)
    }


def drift_report(questions: list[dict] | None = None) -> dict:
    """Compare feed accuracy on the older half of questions with the newer half."""

    questions = questions if questions is not None else load_questions()
    ordered = sorted(questions, key=lambda item: item["modified"] or "")
    mid = len(ordered) // 2
    early = measured_accuracy(ordered[:mid])
    late = measured_accuracy(ordered[mid:])
    shifts = {}
    for source in sorted(set(early) | set(late)):
        if source == MIRROR:
            continue
        if early.get(source, {}).get("n", 0) < 40 or late.get(source, {}).get("n", 0) < 40:
            continue
        shifts[source] = round(late[source]["accuracy"] - early[source]["accuracy"], 6)
    real = any(abs(value) >= 0.05 for value in shifts.values())
    return {
        "kind": "real" if real else "simulated",
        "shifts": shifts,
        "note": (
            "Questions are ordered by the newest feed modified time. A shift of at least "
            "0.05 with 40 judgments on each side is treated as real drift."
            if real
            else "Feed modified times do not move any source by 0.05, so iteration 4 "
            "swaps the nvd and rocky labels. That swap is simulated and labeled as such."
        ),
    }


def _slots(key: str, sellers: int) -> tuple[int, int]:
    seed = zlib.crc32(key.encode()) & 0xFFFFFFFF
    affected = 20 + (seed % 10)
    other = 20 + ((seed + 7) % 10)
    if other == affected:
        other = affected + 1
    return affected, other


def generate_vuln_world(seed: int, train_questions: int = TRAIN_QUESTIONS) -> World:
    questions = load_questions()
    if len(questions) <= train_questions + 20:
        raise RuntimeError(f"vuln slice has {len(questions)} questions")
    order = list(range(len(questions)))
    random.Random(seed).shuffle(order)
    train_idx = order[:train_questions]
    held_idx = order[train_questions:]
    sources = source_names(questions)

    edges: list[Edge] = []
    chains: dict[int, list[Chain]] = {}
    leaf: dict[int, int] = {}
    gold: dict[int, int] = {}
    persons: set[int] = set()
    names: dict[int, str] = {}
    kinds: dict[int, str] = {}
    modified: dict[int, str] = {}
    projects: dict[int, str] = {}
    train_rels: list[int] = []
    held_rels: list[int] = []

    def add(index: int, rel_id: int) -> None:
        question = questions[index]
        base = 900_000_000 + (rel_id - REL_BASE) * 48
        qid = base + 1
        affected_slot, clean_slot = _slots(f"{question['cve']}:{question['version']}", len(sources))
        affected_id = base + affected_slot
        clean_id = base + clean_slot
        leaf[rel_id] = qid
        gold[rel_id] = affected_id if question["gold"] else clean_id
        names[qid] = f"{question['repo']} {question['version']} · {question['cve']}"
        kinds[qid] = "question"
        names[affected_id] = "affected"
        names[clean_id] = "not affected"
        kinds[affected_id] = "verdict"
        kinds[clean_id] = "verdict"
        persons.add(affected_id)
        persons.add(clean_id)
        modified[rel_id] = question["modified"]
        projects[rel_id] = question["repo"]
        chains[rel_id] = []
        ordered = [source for source in sources if source in question["votes"]]
        for slot, source in enumerate(ordered):
            claim = base + 2 + slot
            names[claim] = source
            kinds[claim] = "claim"
            verdict = affected_id if question["votes"][source] else clean_id
            first = len(edges)
            edges.append(Edge(qid, claim, source, rel_id, 0))
            edges.append(Edge(claim, verdict, source, rel_id, 1))
            chains[rel_id].append(Chain(source, rel_id, [first, first + 1], verdict))

    for offset, index in enumerate(train_idx):
        rel_id = REL_BASE + offset
        train_rels.append(rel_id)
        add(index, rel_id)
    for offset, index in enumerate(held_idx):
        rel_id = REL_BASE + train_questions + offset
        held_rels.append(rel_id)
        add(index, rel_id)

    world = World(
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
        projects=projects,
    )
    world.modified = modified  # type: ignore[attr-defined]
    world.question_count = len(questions)  # type: ignore[attr-defined]
    return world


def chronological_batch(world: World, step: int, iters: int, batch_size: int) -> list[int]:
    """Train questions in modified-time order, one slice per iteration."""

    ordered = sorted(world.train_rels, key=lambda rel_id: (world.modified.get(rel_id, ""), rel_id))
    if not ordered:
        return []
    width = max(1, len(ordered) // iters)
    start = min((step - 1) * width, max(0, len(ordered) - 1))
    chunk = ordered[start : start + max(width, batch_size)]
    if len(chunk) >= batch_size:
        return chunk[:batch_size]
    if not chunk:
        return ordered[:batch_size]
    return [chunk[index % len(chunk)] for index in range(batch_size)]


def apply_label_swap(world: World, left: str = "nvd", right: str = "rocky") -> dict[str, int]:
    """Swap two source labels. Endpoints stay put. Simulated drift only."""

    swapped = 0
    for edge in world.edges:
        if edge.source == left:
            edge.source = right
            swapped += 1
        elif edge.source == right:
            edge.source = left
            swapped += 1
    for chains in world.chains.values():
        for chain in chains:
            if chain.name == left:
                chain.name = right
            elif chain.name == right:
                chain.name = left
    world.drifted = True
    return {"swapped_edges": swapped, "left": left, "right": right}


def _affected_id(world: World, rel_id: int) -> int:
    for chain in world.chains[rel_id]:
        if world.names.get(chain.person) == "affected":
            return chain.person
    return world.gold[rel_id]


def majority_hit(world: World, rel_id: int) -> int:
    """Majority of feed verdicts. The modeled mirror does not vote. Ties go to not-affected."""

    affected_id = _affected_id(world, rel_id)
    persons = [chain.person for chain in world.chains[rel_id] if chain.name != MIRROR]
    if not persons:
        return 0
    claimed_yes = sum(1 for person in persons if person == affected_id)
    predicted = claimed_yes > (len(persons) - claimed_yes)
    return int(predicted is (world.gold[rel_id] == affected_id))


def bm25_hit(world: World, rel_id: int) -> int:
    """Prefer the feed whose name matches the tokens nvd / vulnerability."""

    from dreamgraph.bm25 import _scores

    chains = list(world.chains[rel_id])
    if not chains:
        return 0
    documents = [chain.name.replace("_", " ").split() for chain in chains]
    scores = _scores(("nvd", "vulnerability"), documents)
    best = max(range(len(chains)), key=lambda index: (scores[index], -chains[index].person))
    return int(chains[best].person == world.gold[rel_id])


def source_only_hit(world: World, rel_id: int, source: str) -> int:
    """Trust one feed. Abstention predicts not-affected."""

    affected_id = _affected_id(world, rel_id)
    actually = world.gold[rel_id] == affected_id
    chain = next((item for item in world.chains[rel_id] if item.name == source), None)
    if chain is None:
        return int(not actually)
    return int((chain.person == affected_id) is actually)
