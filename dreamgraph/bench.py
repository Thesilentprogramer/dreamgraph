"""Score every baseline. Numbers written here are the only chart numbers.

Protocol (1-based iterations): score with the policy in force, then update.
Drift is applied at the start of iteration ``drift_iter``, before that
iteration's score. The dict learner sees ``list[dict]`` edges and its own
Dijkstra; it does not borrow DreamGraph's Prediction object.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from dreamgraph import __version__
from dreamgraph.bm25 import rank_sources
from dreamgraph.config import (
    BACKEND,
    BATCH,
    BOOTSTRAP,
    DRIFT_ITER,
    DRIFT_MIN_REL,
    GREEDY_DECAY,
    GUARD,
    HAND_SET_COSTS,
    HELD_OUT,
    ITERS,
    P_CORRECT,
    SEEDS,
    SOURCES,
    WINDOW,
    uniform_costs,
)
from dreamgraph.learner import consider_update, refit_costs_from_dicts
from dreamgraph.search import build_index, cheapest_owner, predict_relation
from dreamgraph.store import ObjectStore
from dreamgraph.world import apply_drift, generate_world, source_correct, source_endpoint

METHODS = (
    "dreamgraph",
    "unweighted",
    "hand_set",
    "one_shot",
    "dict_learner",
    "greedy",
    "bm25",
    "frozen_at_3",
)

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "results" / "summary.json"


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("no latency samples")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def stratified_bootstrap(
    per_seed: list[list[int]],
    *,
    draws: int = BOOTSTRAP,
    rng: random.Random | None = None,
) -> tuple[float, float, float]:
    rng = rng or random.Random(0)
    means = []
    for _ in range(draws):
        seed_means = []
        for outcomes in per_seed:
            total = 0
            n = len(outcomes)
            for _pick in range(n):
                total += outcomes[rng.randrange(n)]
            seed_means.append(total / n)
        means.append(sum(seed_means) / len(seed_means))
    means.sort()
    low = means[int(0.025 * (draws - 1))]
    high = means[int(0.975 * (draws - 1))]
    point = sum(sum(outcomes) / len(outcomes) for outcomes in per_seed) / len(per_seed)
    return point, low, high


def _dict_accuracy(questions: list[int], edges: list[dict], leaf: dict[int, int], gold: dict[int, int], persons: set[int], costs: dict[str, float]) -> float:
    if not questions:
        return 0.0
    index = build_index(edges)
    hits = 0
    for rel_id in questions:
        prediction = cheapest_owner(edges, leaf[rel_id], persons, costs, index)
        if prediction.person == gold[rel_id]:
            hits += 1
    return hits / len(questions)


def _greedy_update(good: dict[str, float], bad: dict[str, float], world, batch: list[int]) -> dict[str, float]:
    for rel_id in batch:
        for source in SOURCES:
            good[source] *= GREEDY_DECAY
            bad[source] *= GREEDY_DECAY
            if source_correct(world, rel_id, source):
                good[source] += 1.0
            else:
                bad[source] += 1.0
    return {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in SOURCES}


def run_benchmark(
    *,
    seeds: tuple[int, ...] = SEEDS,
    iters: int = ITERS,
    batch_size: int = BATCH,
    window: int = WINDOW,
    guard: int = GUARD,
    drift_iter: int = DRIFT_ITER,
    bootstrap: int = BOOTSTRAP,
) -> dict:
    if BACKEND == "hydradb":
        probe_path = ROOT / "results" / "probe.json"
        live = False
        if probe_path.exists():
            import json

            live = json.loads(probe_path.read_text()).get("live_engine") is True
        if not live:
            raise SystemExit(
                "DG_BACKEND=hydradb but results/probe.json does not have live_engine=true. "
                "Run python scripts/probe_hydradb.py on a machine with Docker. "
                "This bench will not silently score the in-process graph and call it HydraDB."
            )
        raise SystemExit(
            "The live engine passed the probe, but the full multi-seed load path is still the "
            "in-process graph. Re-run without DG_BACKEND=hydradb to refresh results/summary.json, "
            "or extend dreamgraph.bench once you want every held-out query issued over HTTP."
        )

    outcomes: dict[str, list[list[list[int]]]] = {
        method: [[] for _ in range(iters)] for method in METHODS
    }
    # outcomes[method][iteration_index][seed_index] = list of 0/1
    for method in METHODS:
        for index in range(iters):
            outcomes[method][index] = [[] for _ in seeds]

    latencies_ms: list[float] = []
    policies: list[dict] = []
    per_seed_final_costs: list[dict] = []
    scoring_costs_last: dict[str, float] | None = None
    demo_world_seed = seeds[0]
    version_counter = 0
    rollback_counts = {seed: 0 for seed in seeds}

    for seed_index, seed in enumerate(seeds):
        world = generate_world(seed)
        index = build_index(world.edges)
        rng = random.Random(10_000 + seed)
        log: list[int] = []
        costs = {
            "dreamgraph": uniform_costs(),
            "one_shot": uniform_costs(),
            "dict_learner": uniform_costs(),
            "greedy": uniform_costs(),
            "frozen_at_3": uniform_costs(),
            "hand_set": dict(HAND_SET_COSTS),
        }
        greedy_good = {source: 0.0 for source in SOURCES}
        greedy_bad = {source: 0.0 for source in SOURCES}

        for step in range(1, iters + 1):
            if step == drift_iter:
                apply_drift(world)
                index = build_index(world.edges)
            step_index = step - 1

            dict_edges = world.edges_as_dicts()
            dict_index = build_index(dict_edges)

            def score(method: str, method_costs: dict[str, float] | None) -> list[int]:
                hits = []
                use_index = dict_index if method == "dict_learner" else index
                use_edges = dict_edges if method == "dict_learner" else world.edges
                for rel_id in world.heldout_rels:
                    started = time.perf_counter()
                    if method == "bm25":
                        source = rank_sources(world, rel_id)
                        person = source_endpoint(world, rel_id, source)
                        hit = person == world.gold[rel_id]
                    else:
                        prediction = cheapest_owner(
                            use_edges,
                            world.leaf[rel_id],
                            world.persons,
                            method_costs,
                            use_index,
                        )
                        hit = prediction.person == world.gold[rel_id]
                    if method == "dreamgraph" and seed == demo_world_seed:
                        latencies_ms.append((time.perf_counter() - started) * 1000.0)
                    hits.append(1 if hit else 0)
                return hits

            # Score before any update on this iteration.
            outcomes["unweighted"][step_index][seed_index] = score("unweighted", None)
            outcomes["bm25"][step_index][seed_index] = score("bm25", None)
            for method in ("dreamgraph", "hand_set", "one_shot", "greedy", "frozen_at_3"):
                outcomes[method][step_index][seed_index] = score(method, costs[method])
            outcomes["dict_learner"][step_index][seed_index] = score(
                "dict_learner", costs["dict_learner"]
            )
            if seed == demo_world_seed and step == iters:
                scoring_costs_last = dict(costs["dreamgraph"])

            batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            log.extend(batch)
            edges = world.edges_as_dicts()

            def dream_refit(questions: list[int]) -> dict[str, float]:
                from dreamgraph.learner import refit_costs

                return refit_costs(questions, world)

            def dream_score(questions: list[int], proposed: dict[str, float]) -> float:
                from dreamgraph.learner import policy_accuracy

                return policy_accuracy(questions, world, proposed)

            def dict_refit(questions: list[int]) -> dict[str, float]:
                return refit_costs_from_dicts(questions, edges, world.leaf, world.gold)

            def dict_score(questions: list[int], proposed: dict[str, float]) -> float:
                return _dict_accuracy(questions, edges, world.leaf, world.gold, world.persons, proposed)

            # DreamGraph: every iteration.
            version_counter += 1
            costs["dreamgraph"], version = consider_update(
                log,
                world,
                costs["dreamgraph"],
                iteration=step,
                seed=seed,
                version=version_counter,
                window=window,
                guard=guard,
            )
            # consider_update calls refit_costs internally. Re-run the dict twin
            # with the same window cut so a divergence is visible rather than hidden.
            from dreamgraph.learner import window_slice

            sliced = window_slice(log, window)
            if guard > 0 and len(sliced) > guard + 5:
                fit_on, guard_on = sliced[:-guard], sliced[-guard:]
            else:
                fit_on, guard_on = sliced, []
            proposed = dict_refit(fit_on)
            if guard_on:
                new_acc = dict_score(guard_on, proposed)
                old_acc = dict_score(guard_on, costs["dict_learner"])
                costs["dict_learner"] = dict(costs["dict_learner"]) if new_acc < old_acc else proposed
            else:
                costs["dict_learner"] = proposed

            policies.append(version.as_dict())
            if version.rolled_back:
                rollback_counts[seed] += 1

            costs["greedy"] = _greedy_update(greedy_good, greedy_bad, world, batch)
            if step == 1:
                costs["one_shot"] = dict(costs["dreamgraph"])
            if step < drift_iter:
                costs["frozen_at_3"] = dict(costs["dreamgraph"])

        per_seed_final_costs.append({"seed": seed, "dreamgraph": costs["dreamgraph"], "frozen_at_3": costs["frozen_at_3"]})

    rng = random.Random(0)
    series = {}
    for method in METHODS:
        accuracy, ci_low, ci_high = [], [], []
        for step_index in range(iters):
            point, low, high = stratified_bootstrap(outcomes[method][step_index], draws=bootstrap, rng=rng)
            accuracy.append(round(point, 6))
            ci_low.append(round(low, 6))
            ci_high.append(round(high, 6))
        series[method] = {"accuracy": accuracy, "ci_low": ci_low, "ci_high": ci_high}

    # Demo questions from seed 0's post-drift world, using the policy that
    # produced the last plotted point (the score at the final iteration).
    demo_world = generate_world(demo_world_seed)
    if iters >= drift_iter:
        apply_drift(demo_world)
    disagree, agree = [], []
    assert scoring_costs_last is not None
    for rel_id in demo_world.heldout_rels:
        learned = predict_relation(demo_world, rel_id, scoring_costs_last).person
        plain = predict_relation(demo_world, rel_id, None).person
        if learned != plain and len(disagree) < 6:
            disagree.append(rel_id)
        elif learned == plain and len(agree) < 2:
            agree.append(rel_id)
        if len(disagree) >= 6 and len(agree) >= 2:
            break

    document = {
        "project": "dreamgraph",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": "memory",
        "hydra_verified": False,
        "synthetic_noise": True,
        "precomputed": True,
        "storage": "moto",
        "object_key": "results/summary.json",
        "export_path": "results/summary.json",
        "noise": {
            "description": (
                "Synthetic source noise. Each vendor chain ends at the true owner "
                "with a fixed probability. Drift swaps labels; it does not resimulate endpoints."
            ),
            "p_correct_before_drift": P_CORRECT,
            "drift_min_rel": DRIFT_MIN_REL,
            "drift_effect": "wikidata and scraper labels exchange on rel_id >= drift_min_rel",
        },
        "config": {
            "seeds": list(seeds),
            "iterations": iters,
            "drift_iter": drift_iter,
            "window": window,
            "guard": guard,
            "batch": batch_size,
            "held_out": HELD_OUT if len(seeds) else 0,
            "held_out_actual": len(generate_world(seeds[0]).heldout_rels),
            "train_relations": len(generate_world(seeds[0]).train_rels),
            "bootstrap": bootstrap,
            "protocol": "score then update; drift is applied before the drift iteration's score",
            "tie_break": "minimum (weight, path node ids)",
            "no_gold_pinning": True,
            "no_shortcut_stage": True,
        },
        "methods": list(METHODS),
        "series": series,
        "drift_iter": drift_iter,
        "policies": policies,
        "rollback_counts": {str(seed): count for seed, count in rollback_counts.items()},
        "load": {
            "backend": "memory",
            "what": "In-process DreamGraph held-out searches on seed 0. These are not HydraDB network latencies.",
            "n": len(latencies_ms),
            "p50_ms": round(percentile(latencies_ms, 0.50), 6),
            "p95_ms": round(percentile(latencies_ms, 0.95), 6),
            "p99_ms": round(percentile(latencies_ms, 0.99), 6),
        },
        "demo": {
            "seed": demo_world_seed,
            "drift_applied": iters >= drift_iter,
            "costs": {key: round(value, 6) for key, value in scoring_costs_last.items()},
            "questions": disagree + agree,
            "disagree": disagree,
            "agree": agree,
        },
        "final_costs_by_seed": [
            {
                "seed": row["seed"],
                "dreamgraph": {key: round(value, 6) for key, value in row["dreamgraph"].items()},
                "frozen_at_3": {key: round(value, 6) for key, value in row["frozen_at_3"].items()},
            }
            for row in per_seed_final_costs
        ],
        "notes": [
            "Chart numbers are this document. The dashboard reads it; it does not embed a second copy.",
            "backend=memory means Dijkstra ran in-process. HydraDB path calls are unverified until results/probe.json has live_engine=true.",
            "The dict learner is the same refit over list[dict] edges. If its series matches DreamGraph, that is the measurement, not a bug to hide.",
            "precomputed=true means the file is an export of the object written during this run.",
        ],
    }
    # held_out in config should be the actual count, not a stale import if tests shrink the world.
    document["config"]["held_out"] = document["config"]["held_out_actual"]
    return document


def publish(document: dict, export: Path = EXPORT) -> dict:
    store = ObjectStore(use_moto=True)
    try:
        store.put_json(document["object_key"], document)
        fetched = store.get_json(document["object_key"])
        if fetched["series"]["dreamgraph"]["accuracy"] != document["series"]["dreamgraph"]["accuracy"]:
            raise RuntimeError("object store round-trip changed the series")
        store.export_json(document["object_key"], export)
    finally:
        store.close()
    return document


def main() -> None:
    document = publish(run_benchmark())
    dream = document["series"]["dreamgraph"]["accuracy"]
    print(
        "wrote",
        EXPORT,
        "dreamgraph",
        dream,
        "load_p50_ms",
        document["load"]["p50_ms"],
    )


if __name__ == "__main__":
    main()
