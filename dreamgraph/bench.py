"""Score every baseline. Numbers written here are the only chart numbers.

Protocol (1-based iterations): score with the policy in force, then update.
Drift is applied at the start of iteration ``drift_iter``, before that
iteration's score. The dict learner sees ``list[dict]`` edges and its own
Dijkstra; it does not borrow DreamGraph's Prediction object.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from pathlib import Path

from dreamgraph import __version__
from dreamgraph.bm25 import rank_chain
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
    CHAIN_P_TRUE,
    SEEDS,
    SOURCES,
    WINDOW,
    uniform_costs,
)
from dreamgraph.hydra_graph import HydraGraph, concurrent_latencies
from dreamgraph.learner import consider_update, refit_costs_from_dicts
from dreamgraph.search import build_index, cheapest_owner, is_correct, predict_relation
from dreamgraph.store import ObjectStore
from dreamgraph.world import apply_drift, edge_feedback, generate_world

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
        for source, correct in edge_feedback(world, rel_id):
            if correct:
                good[source] += 1.0
            else:
                bad[source] += 1.0
    return {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in SOURCES}


def _hops(prediction) -> int:
    return max(0, len(prediction.path) - 1)


def _load_block(use_hydra: bool, src: int) -> dict:
    if not use_hydra:
        return {
            "backend": "memory",
            "what": "In-process search. Re-run with DG_BACKEND=hydradb for engine latencies.",
            "n": 0,
            "clients": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
        }
    from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL

    samples = concurrent_latencies(HYDRA_URL, HYDRA_TOKEN, src, rounds=30, clients=20)
    return {
        "backend": "hydradb",
        "what": "20 concurrent clients, each issuing 30 weighted algo.SSpaths calls against the live node.",
        "clients": 20,
        "rounds_per_client": 30,
        "n": len(samples),
        "p50_ms": round(percentile(samples, 0.50), 4),
        "p95_ms": round(percentile(samples, 0.95), 4),
        "p99_ms": round(percentile(samples, 0.99), 4),
    }


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
    use_hydra = BACKEND == "hydradb"
    hydra: HydraGraph | None = None
    if use_hydra:
        import json
        import urllib.request

        probe_path = ROOT / "results" / "probe.json"
        live = probe_path.exists() and json.loads(probe_path.read_text()).get("live_engine") is True
        if not live:
            raise SystemExit(
                "DG_BACKEND=hydradb but results/probe.json does not have live_engine=true. "
                "Run python scripts/probe_hydradb.py."
            )
        try:
            with urllib.request.urlopen("http://127.0.0.1:8443/healthz", timeout=3) as response:
                if response.status != 200:
                    raise SystemExit("HydraDB /healthz did not return 200")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"HydraDB is not answering on :8443 ({exc})") from exc
        from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL

        hydra = HydraGraph(HYDRA_URL, HYDRA_TOKEN)

    outcomes: dict[str, list[list[list[int]]]] = {method: [] for method in METHODS}
    hop3: dict[str, list[list[list[int]]]] = {method: [] for method in METHODS}
    for method in METHODS:
        outcomes[method] = [[[] for _ in seeds] for _ in range(iters)]
        hop3[method] = [[[] for _ in seeds] for _ in range(iters)]

    policies: list[dict] = []
    load_src = 0
    per_seed_final_costs: list[dict] = []
    scoring_costs_last: dict[str, float] | None = None
    demo_world_seed = seeds[0]
    version_counter = 0
    rollback_counts = {seed: 0 for seed in seeds}

    for seed_index, seed in enumerate(seeds):
        world = generate_world(seed)
        if hydra is not None:
            print(f"loading seed {seed} into HydraDB", flush=True)
            hydra.load(world)
        index = build_index(world.edges)
        rng = random.Random(10_000 + seed)
        load_src = world.leaf[world.heldout_rels[0]]
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
                if hydra is not None:
                    drifted_rels = [
                        rel
                        for rel in world.train_rels + world.heldout_rels
                        if rel >= DRIFT_MIN_REL
                    ]
                    print(f"seed {seed} drift swap on {len(drifted_rels)} relations", flush=True)
                    hydra.swap_drift_labels(drifted_rels)
            step_index = step - 1

            dict_edges = world.edges_as_dicts()
            dict_index = build_index(dict_edges)

            def score(method: str, method_costs: dict[str, float] | None) -> tuple[list[int], list[int]]:
                hits = []
                hops = []
                via_hydra = hydra is not None and method not in {"dict_learner", "bm25"}
                if via_hydra and method_costs is not None:
                    hydra.stamp_source_costs(method_costs)
                for rel_id in world.heldout_rels:
                    if method == "bm25":
                        person, sources = rank_chain(world, rel_id)
                        hit = person == world.gold[rel_id]
                        hop_n = len(sources)
                    elif via_hydra:
                        prediction = hydra.owner(world, rel_id, method_costs)
                        hit = is_correct(world, rel_id, prediction)
                        hop_n = _hops(prediction)
                    else:
                        use_index = dict_index if method == "dict_learner" else index
                        use_edges = dict_edges if method == "dict_learner" else world.edges
                        prediction = cheapest_owner(
                            use_edges,
                            world.leaf[rel_id],
                            world.persons,
                            method_costs,
                            use_index,
                        )
                        hit = prediction.person == world.gold[rel_id]
                        hop_n = _hops(prediction)
                    hits.append(1 if hit else 0)
                    hops.append(1 if hop_n >= 3 else 0)
                return hits, hops

            def take(method: str, method_costs: dict[str, float] | None) -> None:
                hits, hops = score(method, method_costs)
                outcomes[method][step_index][seed_index] = hits
                hop3[method][step_index][seed_index] = hops

            # Score before any update on this iteration.
            take("unweighted", None)
            take("bm25", None)
            for method in ("dreamgraph", "hand_set", "one_shot", "greedy", "frozen_at_3"):
                take(method, costs[method])
            take("dict_learner", costs["dict_learner"])
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
                return refit_costs_from_dicts(questions, world.chains_as_dicts(), world.gold)

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
        hop_rates = []
        for step_index in range(iters):
            pooled = [bit for seed_rows in hop3[method][step_index] for bit in seed_rows]
            hop_rates.append(round(sum(pooled) / len(pooled), 6) if pooled else 0.0)
        series[method] = {
            "accuracy": accuracy,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "hop3_rate": hop_rates,
        }

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
        "backend": "hydradb" if use_hydra else "memory",
        "hydra_verified": use_hydra,
        "synthetic_noise": True,
        "precomputed": True,
        "storage": "moto",
        "object_key": "results/summary.json",
        "export_path": "results/summary.json",
        "noise": {
            "description": (
                "Synthetic chain noise. The 3-hop chain usually names the true owner; "
                "two 2-hop chains compete. Drift swaps wikidata and scraper labels and "
                "does not move the people. The answer is the person at the end of the "
                "minimum summed edge-cost path."
            ),
            "chain_p_true": CHAIN_P_TRUE,
            "drift_min_rel": DRIFT_MIN_REL,
            "drift_effect": "wikidata and scraper labels exchange on rel_id >= drift_min_rel",
            "path_cost": "sum of per-edge costs; each edge stores the learned cost of its current source",
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
        "load": _load_block(use_hydra, load_src),
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
            (
                "DreamGraph, unweighted, hand-set, one-shot, greedy, and frozen answers are algo.SSpaths "
                "round trips. The dict learner is the same refit and the same sum, evaluated on plain dicts."
                if use_hydra
                else "backend=memory means Dijkstra ran in-process."
            ),
            "hop3_rate is the share of answers whose chosen path has 3 edges. Unweighted prefers the 2-hop chains.",
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
