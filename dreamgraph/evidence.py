"""Book-slice benchmark, poison scenario, and the 1-hop replay.

Chart numbers for the synthetic HydraDB series stay in ``results/summary.json``.
This module adds evidence beside them. It does not refit those HydraDB accuracies.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from dreamgraph.bench import EXPORT, stratified_bootstrap
from dreamgraph.bm25 import rank_chain
from dreamgraph.config import BATCH, BOOTSTRAP, DRIFT_ITER, GREEDY_DECAY, GUARD, ITERS, SEEDS, WINDOW
from dreamgraph.hypotheses import evaluate
from dreamgraph.learner import consider_update, refit_costs, window_slice
from dreamgraph.public_world import (
    BOOK_HAND_SET,
    BOOK_SOURCES,
    books_by_isbn,
    generate_public_world,
    source_hit_rates,
)
from dreamgraph.search import build_index, cheapest_owner, one_hop_owner
from dreamgraph.world import World, apply_drift, edge_feedback, generate_world

ROOT = Path(__file__).resolve().parents[1]
ONE_HOP_PATH = ROOT / "results" / "one_hop.json"
PUBLIC_PATH = ROOT / "results" / "public_summary.json"
POISON_PATH = ROOT / "results" / "poison.json"
HYPOTHESIS_PATH = ROOT / "results" / "hypotheses.json"

POISON_SOURCE = "wikidata"
POISON_FRIEND = "scraper"
POISON_ITER = 4


def _hits(questions, predict) -> tuple[list[int], list[int]]:
    hits = []
    hops = []
    for rel_id in questions:
        person, hop_n = predict(rel_id)
        hits.append(person)
        hops.append(hop_n)
    return hits, hops


def _mean(bits: list[int]) -> float:
    if not bits:
        return 0.0
    return sum(bits) / len(bits)


def _series(outcomes: dict, hop3: dict, iters: int, bootstrap: int, rng: random.Random) -> dict:
    series = {}
    for method in outcomes:
        accuracy, low, high, hops = [], [], [], []
        for step in range(iters):
            point, lo, hi = stratified_bootstrap(outcomes[method][step], draws=bootstrap, rng=rng)
            accuracy.append(round(point, 6))
            low.append(round(lo, 6))
            high.append(round(hi, 6))
            pooled = [bit for seed_rows in hop3[method][step] for bit in seed_rows]
            hops.append(round(sum(pooled) / len(pooled), 6) if pooled else 0.0)
        series[method] = {"accuracy": accuracy, "ci_low": low, "ci_high": high, "hop3_rate": hops}
    return series


def _blank(methods: tuple[str, ...], iters: int, seeds: int) -> tuple[dict, dict]:
    outcomes = {method: [[[] for _ in range(seeds)] for _ in range(iters)] for method in methods}
    hop3 = {method: [[[] for _ in range(seeds)] for _ in range(iters)] for method in methods}
    return outcomes, hop3


def _greedy(good: dict[str, float], bad: dict[str, float], world: World, batch: list[int], sources: tuple[str, ...]) -> dict[str, float]:
    for rel_id in batch:
        for source in sources:
            good[source] *= GREEDY_DECAY
            bad[source] *= GREEDY_DECAY
        for source, correct in edge_feedback(world, rel_id):
            if correct:
                good[source] += 1.0
            else:
                bad[source] += 1.0
    return {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in sources}


def _dict_bits(questions, edges, index, leaf, gold, persons, costs):
    hits, hops = [], []
    for rel_id in questions:
        prediction = cheapest_owner(edges, leaf[rel_id], persons, costs, index)
        hits.append(1 if prediction.person == gold[rel_id] else 0)
        hops.append(1 if len(prediction.path) - 1 >= 3 else 0)
    return hits, hops


def _seller_rates(world: World) -> dict[str, float]:
    rates = {}
    for source in BOOK_SOURCES:
        hits = total = 0
        for rel_id in world.heldout_rels:
            chain = next((item for item in world.chains[rel_id] if item.name == source), None)
            if chain is None:
                continue
            total += 1
            hits += int(chain.person == world.gold[rel_id])
        rates[source] = None if total == 0 else round(hits / total, 6)
    return rates


def replay_one_hop(
    *,
    seeds: tuple[int, ...] = SEEDS,
    iters: int = ITERS,
    batch_size: int = BATCH,
    window: int = WINDOW,
    guard: int = GUARD,
    drift_iter: int = DRIFT_ITER,
    bootstrap: int = BOOTSTRAP,
) -> dict:
    """Same synthetic updates as the published loop. Score 1-hop beside them."""

    methods = ("dreamgraph", "one_hop")
    outcomes, hop3 = _blank(methods, iters, len(seeds))
    for seed_index, seed in enumerate(seeds):
        world = generate_world(seed)
        rng = random.Random(10_000 + seed)
        log: list[int] = []
        costs = {source: 1.0 for source in ("wikidata", "registry", "scraper")}
        version = 0
        for step in range(1, iters + 1):
            if step == drift_iter:
                apply_drift(world)
            index = build_index(world.edges)

            def full(rel_id: int, costs=costs, index=index, world=world):
                prediction = cheapest_owner(world.edges, world.leaf[rel_id], world.persons, costs, index)
                hit = 1 if prediction.person == world.gold[rel_id] else 0
                return hit, 1 if len(prediction.path) - 1 >= 3 else 0

            def hop(rel_id: int, costs=costs, world=world):
                prediction = one_hop_owner(world, rel_id, costs)
                hit = 1 if prediction.person == world.gold[rel_id] else 0
                return hit, 1 if len(prediction.path) - 1 >= 3 else 0

            for method, fn in (("dreamgraph", full), ("one_hop", hop)):
                hits, hops = _hits(world.heldout_rels, fn)
                outcomes[method][step - 1][seed_index] = hits
                hop3[method][step - 1][seed_index] = hops

            batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            log.extend(batch)
            version += 1
            costs, _snapshot = consider_update(
                log, world, costs, iteration=step, seed=seed, version=version, window=window, guard=guard
            )
        print(f"one-hop replay seed {seed} done", flush=True)
    return {
        "protocol": "memory replay of the synthetic loop; drift before the drift iteration's score; 1-hop uses DreamGraph's costs",
        "series": _series(outcomes, hop3, iters, bootstrap, random.Random(0)),
    }


def run_book(
    *,
    seeds: tuple[int, ...] = SEEDS,
    iters: int = ITERS,
    batch_size: int = BATCH,
    window: int = WINDOW,
    guard: int = GUARD,
    bootstrap: int = BOOTSTRAP,
) -> dict:
    methods = (
        "dreamgraph",
        "unweighted",
        "hand_set",
        "one_shot",
        "dict_learner",
        "greedy",
        "bm25",
        "frozen_at_3",
        "one_hop",
    )
    outcomes, hop3 = _blank(methods, iters, len(seeds))
    policies = []
    rollback_counts = {seed: 0 for seed in seeds}
    final_costs = []
    seller_rows = []
    version_counter = 0
    sources = BOOK_SOURCES

    for seed_index, seed in enumerate(seeds):
        world = generate_public_world(seed)
        rng = random.Random(20_000 + seed)
        log: list[int] = []
        uniform = {source: 1.0 for source in sources}
        costs = {
            "dreamgraph": dict(uniform),
            "one_shot": dict(uniform),
            "dict_learner": dict(uniform),
            "greedy": dict(uniform),
            "frozen_at_3": dict(uniform),
            "naive": dict(uniform),
            "hand_set": dict(BOOK_HAND_SET),
        }
        good = {source: 0.0 for source in sources}
        bad = {source: 0.0 for source in sources}
        index = build_index(world.edges)
        dict_edges = world.edges_as_dicts()
        dict_index = build_index(dict_edges)
        scoring_costs = None

        for step in range(1, iters + 1):
            def predict(method: str, method_costs, step=step):
                def one(rel_id: int):
                    if method == "bm25":
                        person, labels = rank_chain(world, rel_id)
                        return (1 if person == world.gold[rel_id] else 0), (1 if len(labels) >= 3 else 0)
                    if method == "one_hop":
                        prediction = one_hop_owner(world, rel_id, method_costs)
                    elif method == "dict_learner":
                        prediction = cheapest_owner(dict_edges, world.leaf[rel_id], world.persons, method_costs, dict_index)
                    else:
                        prediction = cheapest_owner(world.edges, world.leaf[rel_id], world.persons, method_costs, index)
                    hit = 1 if prediction.person == world.gold[rel_id] else 0
                    return hit, 1 if len(prediction.path) - 1 >= 3 else 0

                return one

            plan = {
                "unweighted": None,
                "bm25": None,
                "one_hop": costs["dreamgraph"],
                "dreamgraph": costs["dreamgraph"],
                "hand_set": costs["hand_set"],
                "one_shot": costs["one_shot"],
                "greedy": costs["greedy"],
                "frozen_at_3": costs["frozen_at_3"],
                "dict_learner": costs["dict_learner"],
            }
            for method, method_costs in plan.items():
                hits, hops = _hits(world.heldout_rels, predict(method, method_costs))
                outcomes[method][step - 1][seed_index] = hits
                hop3[method][step - 1][seed_index] = hops
            if seed == seeds[0] and step == iters:
                scoring_costs = dict(costs["dreamgraph"])

            batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            log.extend(batch)
            version_counter += 1
            before = dict(costs["dreamgraph"])
            costs["dreamgraph"], version = consider_update(
                log, world, costs["dreamgraph"], iteration=step, seed=seed, version=version_counter, window=window, guard=guard
            )
            version.heldout_before = _mean(outcomes["dreamgraph"][step - 1][seed_index])
            proposed_hits, _ = _hits(world.heldout_rels, predict("dreamgraph", version.proposed_costs))
            version.heldout_after = _mean(proposed_hits)
            policies.append(version.as_dict())
            if version.rolled_back:
                rollback_counts[seed] += 1

            sliced = window_slice(log, window)
            if guard > 0 and len(sliced) > guard + 5:
                fit_on, guard_on = sliced[:-guard], sliced[-guard:]
            else:
                fit_on, guard_on = sliced, []
            proposed = refit_costs(fit_on, world)
            if guard_on:
                new_hits, _ = _dict_bits(guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, proposed)
                old_hits, _ = _dict_bits(guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, costs["dict_learner"])
                costs["dict_learner"] = dict(costs["dict_learner"]) if _mean(new_hits) < _mean(old_hits) else proposed
            else:
                costs["dict_learner"] = proposed
            costs["greedy"] = _greedy(good, bad, world, batch, sources)
            if step == 1:
                costs["one_shot"] = dict(costs["dreamgraph"])
            if step < DRIFT_ITER:
                costs["frozen_at_3"] = dict(costs["dreamgraph"])
            del before

        final_costs.append({"seed": seed, "dreamgraph": {key: round(value, 6) for key, value in costs["dreamgraph"].items()}})
        seller_rows.append(_seller_rates(world))
        if seed == seeds[0]:
            demo_world = world
            demo_costs = scoring_costs
        print(f"book seed {seed} done", flush=True)

    disagree = []
    assert demo_costs is not None
    for rel_id in demo_world.heldout_rels:
        learned = cheapest_owner(demo_world.edges, demo_world.leaf[rel_id], demo_world.persons, demo_costs).person
        plain = cheapest_owner(demo_world.edges, demo_world.leaf[rel_id], demo_world.persons, None).person
        if learned != plain:
            disagree.append(rel_id)
    questions = list(disagree[:6])
    for rel_id in demo_world.heldout_rels:
        if rel_id not in questions:
            questions.append(rel_id)
        if len(questions) >= 8:
            break
    agree = [rel_id for rel_id in questions if rel_id not in disagree]
    seller_mean = {}
    for source in BOOK_SOURCES:
        vals = [row[source] for row in seller_rows if row[source] is not None]
        seller_mean[source] = None if not vals else round(sum(vals) / len(vals), 6)

    books = books_by_isbn()
    return {
        "dataset": "book",
        "citation": (
            "Yin, Han, and Yu, TKDE 2008, claims; Dong, Berti-Equille, and Srivastava, VLDB 2009, "
            "gold author lists from book covers. Cached slice: data/book/claims.jsonl."
        ),
        "license_note": "Research distribution at https://lunadong.com/fusionDataSets.htm. See data/book/PROVENANCE.md.",
        "sources": list(BOOK_SOURCES),
        "match_rule": "token Jaccard >= 0.5 on tokens longer than 2 characters, excluding 'and' and 'the'",
        "encoding": (
            "Each seller is a 2-edge chain book → listing → author. Both edges carry that seller's "
            "learned cost. Path length does not depend on correctness. Unweighted search tie-breaks "
            "on node ids, and listing ids follow alphabetical seller order, so Revaluation Books wins "
            "ties when it listed the book."
        ),
        "source_accuracy_on_slice": source_hit_rates(books),
        "slice_books": len(books),
        "seller_heldout_mean": seller_mean,
        "config": {
            "seeds": list(seeds),
            "iterations": iters,
            "window": window,
            "guard": guard,
            "batch": batch_size,
            "train_books": len(generate_public_world(seeds[0]).train_rels),
            "held_out": len(generate_public_world(seeds[0]).heldout_rels),
            "bootstrap": bootstrap,
            "protocol": "score then update; no label drift; same window and guard as the synthetic loop",
            "hand_set": BOOK_HAND_SET,
            "hand_set_rule": "fixed volume prior, not gold accuracy",
        },
        "methods": list(methods),
        "series": _series(outcomes, hop3, iters, bootstrap, random.Random(1)),
        "policies": policies,
        "rollback_counts": {str(seed): count for seed, count in rollback_counts.items()},
        "final_costs_by_seed": final_costs,
        "demo": {
            "seed": seeds[0],
            "costs": {key: round(value, 6) for key, value in demo_costs.items()},
            "questions": questions,
            "disagree": [rel_id for rel_id in questions if rel_id in disagree],
            "agree": agree,
        },
        "notes": [
            "1-hop lookup uses DreamGraph's learned costs and only the first edge. On this encoding both edges of a chain share a seller, so the sum ranks sellers the same way.",
            "The dict learner minimizes that same sum outside HydraDB.",
            "Seller accuracies on the full slice are descriptive. They are not written onto edges.",
        ],
    }


def run_poison(
    *,
    seeds: tuple[int, ...] = SEEDS,
    iters: int = ITERS,
    batch_size: int = BATCH,
    window: int = WINDOW,
    guard: int = GUARD,
    bootstrap: int = BOOTSTRAP,
    poison_iter: int = POISON_ITER,
) -> dict:
    methods = ("dreamgraph", "dict_learner", "naive", "greedy", "unweighted", "frozen_at_3", "one_hop")
    outcomes, hop3 = _blank(methods, iters, len(seeds))
    policies = []
    rollback_counts = {seed: 0 for seed in seeds}
    version_counter = 0
    sources = ("wikidata", "registry", "scraper")

    for seed_index, seed in enumerate(seeds):
        world = generate_world(seed)
        rng = random.Random(30_000 + seed)
        log: list[int] = []
        uniform = {source: 1.0 for source in sources}
        costs = {name: dict(uniform) for name in ("dreamgraph", "dict_learner", "naive", "greedy", "frozen_at_3")}
        good = {source: 0.0 for source in sources}
        bad = {source: 0.0 for source in sources}
        index = build_index(world.edges)
        dict_edges = world.edges_as_dicts()
        dict_index = build_index(dict_edges)

        for step in range(1, iters + 1):
            if step == poison_iter:
                world.poison_source = POISON_SOURCE
                world.poison_false_friend = POISON_FRIEND

            def predict(method: str, method_costs):
                def one(rel_id: int):
                    if method == "one_hop":
                        prediction = one_hop_owner(world, rel_id, method_costs)
                    elif method == "dict_learner":
                        prediction = cheapest_owner(dict_edges, world.leaf[rel_id], world.persons, method_costs, dict_index)
                    else:
                        prediction = cheapest_owner(world.edges, world.leaf[rel_id], world.persons, method_costs, index)
                    hit = 1 if prediction.person == world.gold[rel_id] else 0
                    return hit, 1 if len(prediction.path) - 1 >= 3 else 0

                return one

            plan = {
                "unweighted": None,
                "one_hop": costs["dreamgraph"],
                "dreamgraph": costs["dreamgraph"],
                "dict_learner": costs["dict_learner"],
                "naive": costs["naive"],
                "greedy": costs["greedy"],
                "frozen_at_3": costs["frozen_at_3"],
            }
            for method, method_costs in plan.items():
                hits, hops = _hits(world.heldout_rels, predict(method, method_costs))
                outcomes[method][step - 1][seed_index] = hits
                hop3[method][step - 1][seed_index] = hops

            batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            log.extend(batch)
            version_counter += 1
            before_costs = dict(costs["dreamgraph"])
            costs["dreamgraph"], version = consider_update(
                log, world, costs["dreamgraph"], iteration=step, seed=seed, version=version_counter, window=window, guard=guard
            )
            version.heldout_before = _mean(outcomes["dreamgraph"][step - 1][seed_index])
            proposed_hits, _ = _hits(world.heldout_rels, predict("dreamgraph", version.proposed_costs))
            version.heldout_after = _mean(proposed_hits)
            # The plotted point used the pre-update policy. heldout_before is that point.
            # heldout_after is the held-out accuracy the rejected or accepted proposal would score.
            del before_costs
            policies.append(version.as_dict())
            if version.rolled_back:
                rollback_counts[seed] += 1

            sliced = window_slice(log, window)
            if guard > 0 and len(sliced) > guard + 5:
                fit_on, guard_on = sliced[:-guard], sliced[-guard:]
            else:
                fit_on, guard_on = sliced, []
            proposed = refit_costs(fit_on, world)
            if guard_on:
                new_hits, _ = _dict_bits(guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, proposed)
                old_hits, _ = _dict_bits(
                    guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, costs["dict_learner"]
                )
                costs["dict_learner"] = dict(costs["dict_learner"]) if _mean(new_hits) < _mean(old_hits) else proposed
            else:
                costs["dict_learner"] = proposed
            costs["naive"] = refit_costs(sliced, world)
            costs["greedy"] = _greedy(good, bad, world, batch, sources)
            if step < poison_iter:
                costs["frozen_at_3"] = dict(costs["dreamgraph"])
        print(f"poison seed {seed} rollbacks {rollback_counts[seed]}", flush=True)

    series = _series(outcomes, hop3, iters, bootstrap, random.Random(2))
    receipts = [row for row in policies if row["rolled_back"]]
    return {
        "scenario": (
            "From iteration 4 on, train feedback treats wikidata as always wrong and scraper as always right. "
            "Held-out edges and gold people do not change. A naive refit trusts the lie. The guard compares "
            "the proposal with the current policy on the last 20 questions of the window, scored against the true owner."
        ),
        "poison_iter": poison_iter,
        "poison_source": POISON_SOURCE,
        "poison_false_friend": POISON_FRIEND,
        "config": {
            "seeds": list(seeds),
            "iterations": iters,
            "window": window,
            "guard": guard,
            "batch": batch_size,
            "held_out": len(generate_world(seeds[0]).heldout_rels),
            "bootstrap": bootstrap,
            "protocol": "score then update; poison flag flips train feedback from the poison iteration onward; no label drift",
        },
        "methods": list(methods),
        "series": series,
        "policies": policies,
        "receipts": receipts,
        "rollback_count": len(receipts),
        "rollback_counts": {str(seed): count for seed, count in rollback_counts.items()},
        "notes": [
            "Naive fits the whole trailing window and always accepts.",
            "Frozen-after-3 copies DreamGraph only while the poison flag is still off.",
            "1-hop is scored with DreamGraph's guarded costs.",
            "Receipts record guard accuracy and held-out accuracy before and after the proposal.",
        ],
    }


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def merge_summary(published: dict, one_hop: dict, public: dict, poison: dict, hypotheses: list[dict]) -> dict:
    dream = list(published["series"]["dreamgraph"]["accuracy"])
    published["series"]["one_hop"] = one_hop["series"]["one_hop"]
    published["ablations"] = {
        "note": (
            "1-hop lookup ranks chains by the learned cost of the first edge and does not call algo.SSpaths. "
            "Unweighted search counts hops. DreamGraph sums learned edge costs; the published synthetic run did that sum inside HydraDB. "
            "The dict learner sums the same costs outside the engine, which is why its accuracies match."
        ),
        "synthetic": {
            "one_hop": one_hop["series"]["one_hop"]["accuracy"][-1],
            "unweighted": published["series"]["unweighted"]["accuracy"][-1],
            "dreamgraph": published["series"]["dreamgraph"]["accuracy"][-1],
            "dict_learner": published["series"]["dict_learner"]["accuracy"][-1],
            "one_hop_hop3": one_hop["series"]["one_hop"]["hop3_rate"][-1],
            "dreamgraph_hop3": published["series"]["dreamgraph"]["hop3_rate"][-1],
            "unweighted_hop3": published["series"]["unweighted"]["hop3_rate"][-1],
            "replay_dreamgraph": one_hop["series"]["dreamgraph"]["accuracy"][-1],
            "replay_matches_published": one_hop.get("matches_published_dreamgraph"),
        },
        "book": {
            method: public["series"][method]["accuracy"][-1]
            for method in public["methods"]
        },
    }
    published["public"] = public
    published["poison"] = {
        key: poison[key]
        for key in (
            "scenario",
            "poison_iter",
            "poison_source",
            "poison_false_friend",
            "config",
            "methods",
            "series",
            "receipts",
            "rollback_count",
            "rollback_counts",
            "notes",
        )
    }
    # The full policy list is large; the dashboard timeline reads receipts plus a short tail.
    published["poison"]["policies"] = poison["policies"]
    published["hypotheses"] = hypotheses
    published["evidence_generated_at"] = datetime.now(timezone.utc).isoformat()
    if published["series"]["dreamgraph"]["accuracy"] != dream:
        raise RuntimeError("evidence merge changed the published DreamGraph series")
    return published


VULN_PATH = ROOT / "results" / "vuln_summary.json"
VULN_POISON_PATH = ROOT / "results" / "vuln_poison.json"


def main() -> None:
    from dreamgraph.vuln_bench import run_vuln, run_vuln_poison

    published = json.loads(EXPORT.read_text())
    dream = list(published["series"]["dreamgraph"]["accuracy"])
    one_hop = json.loads(ONE_HOP_PATH.read_text())
    poison = json.loads(POISON_PATH.read_text())
    vuln = run_vuln()
    vuln_poison = run_vuln_poison()
    hypotheses = evaluate(published, one_hop, vuln, poison, vuln_poison)
    _write(VULN_PATH, vuln)
    _write(VULN_POISON_PATH, vuln_poison)
    _write(HYPOTHESIS_PATH, {"items": hypotheses})
    published.pop("public", None)
    published["vuln"] = vuln
    published["vuln_poison"] = {
        key: vuln_poison[key]
        for key in (
            "scenario",
            "poison_iter",
            "poison_source",
            "poison_false_friend",
            "config",
            "methods",
            "series",
            "receipts",
            "policies",
            "rollback_count",
            "rollback_counts",
        )
        if key in vuln_poison
    }
    published["hypotheses"] = hypotheses
    published["evidence_generated_at"] = datetime.now(timezone.utc).isoformat()
    if "ablations" not in published:
        published["ablations"] = {}
    published["ablations"]["vuln"] = {
        method: vuln["series"][method]["accuracy"][-1] for method in vuln["methods"]
    }
    if published["series"]["dreamgraph"]["accuracy"] != dream:
        raise RuntimeError("evidence merge changed the published DreamGraph series")
    _write(EXPORT, published)
    for item in hypotheses:
        print(f"{item['id']} {item['verdict']} {item['observed']}", flush=True)
    print("vuln final", vuln["series"]["dreamgraph"]["accuracy"][-1], flush=True)
    print("vuln poison rollbacks", vuln_poison["rollback_count"], flush=True)


if __name__ == "__main__":
    main()
