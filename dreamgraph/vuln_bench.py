"""RSI loop on the vulnerability slice. Numbers come from this module."""

from __future__ import annotations

import random

from dreamgraph.config import BATCH, BOOTSTRAP, DRIFT_ITER, GUARD, ITERS, SEEDS, WINDOW
from dreamgraph.learner import consider_update, refit_costs, window_slice
from dreamgraph.search import build_index, cheapest_owner, one_hop_owner
from dreamgraph.vuln_world import (
    MIRROR,
    apply_label_swap,
    bm25_hit,
    chronological_batch,
    drift_report,
    generate_vuln_world,
    hand_set_costs,
    load_questions,
    majority_hit,
    measured_accuracy,
    source_only_hit,
)


def _run(
    *,
    poison: bool,
    seeds: tuple[int, ...],
    iters: int,
    batch_size: int,
    window: int,
    guard: int,
    bootstrap: int,
) -> dict:
    from dreamgraph.evidence import _dict_bits, _greedy, _hits, _mean, _series

    questions = load_questions()
    costs_prior = hand_set_costs(questions)
    sources = tuple(costs_prior)
    report = drift_report(questions)
    simulate = (not poison) and report["kind"] == "simulated"
    methods = (
        ("dreamgraph", "dict_learner", "naive", "greedy", "unweighted", "frozen_at_3", "one_hop")
        if poison
        else (
            "dreamgraph",
            "unweighted",
            "hand_set",
            "one_shot",
            "dict_learner",
            "greedy",
            "bm25",
            "frozen_at_3",
            "one_hop",
            "majority",
            "nvd_only",
            "ghsa_only",
        )
    )
    from dreamgraph.evidence import _blank

    outcomes, hop3 = _blank(methods, iters, len(seeds))
    policies = []
    rollback_counts = {seed: 0 for seed in seeds}
    final_costs = []
    version_counter = 0
    demo = None

    for seed_index, seed in enumerate(seeds):
        world = generate_vuln_world(seed)
        rng = random.Random(40_000 + seed)
        log: list[int] = []
        uniform = {source: 1.0 for source in sources}
        costs = {name: dict(uniform) for name in ("dreamgraph", "one_shot", "dict_learner", "greedy", "frozen_at_3", "naive")}
        costs["hand_set"] = dict(costs_prior)
        good = {source: 0.0 for source in sources}
        bad = {source: 0.0 for source in sources}
        index = build_index(world.edges)
        dict_edges = world.edges_as_dicts()
        dict_index = build_index(dict_edges)
        scoring_costs = None

        for step in range(1, iters + 1):
            if poison and step == DRIFT_ITER:
                world.poison_source = "nvd"
                world.poison_false_friend = MIRROR
            if simulate and step == DRIFT_ITER:
                apply_label_swap(world)
                index = build_index(world.edges)
                dict_edges = world.edges_as_dicts()
                dict_index = build_index(dict_edges)

            def predict(method: str, method_costs):
                def one(rel_id: int):
                    if method == "majority":
                        return majority_hit(world, rel_id), 0
                    if method == "nvd_only":
                        return source_only_hit(world, rel_id, "nvd"), 0
                    if method == "ghsa_only":
                        return source_only_hit(world, rel_id, "ghsa"), 0
                    if method == "bm25":
                        return bm25_hit(world, rel_id), 0
                    if method == "one_hop":
                        prediction = one_hop_owner(world, rel_id, method_costs)
                    elif method == "dict_learner":
                        prediction = cheapest_owner(
                            dict_edges, world.leaf[rel_id], world.persons, method_costs, dict_index
                        )
                    else:
                        prediction = cheapest_owner(
                            world.edges, world.leaf[rel_id], world.persons, method_costs, index
                        )
                    hit = 1 if prediction.person == world.gold[rel_id] else 0
                    return hit, 1 if len(prediction.path) - 1 >= 3 else 0

                return one

            plan = {
                "unweighted": None,
                "one_hop": costs["dreamgraph"],
                "dreamgraph": costs["dreamgraph"],
                "hand_set": costs["hand_set"],
                "one_shot": costs["one_shot"],
                "greedy": costs["greedy"],
                "frozen_at_3": costs["frozen_at_3"],
                "dict_learner": costs["dict_learner"],
                "naive": costs["naive"],
                "majority": None,
                "nvd_only": None,
                "ghsa_only": None,
                "bm25": None,
            }
            for method in methods:
                hits, hops = _hits(world.heldout_rels, predict(method, plan[method]))
                outcomes[method][step - 1][seed_index] = hits
                hop3[method][step - 1][seed_index] = hops
            if seed == seeds[0] and step == iters:
                scoring_costs = dict(costs["dreamgraph"])

            if poison:
                batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            else:
                batch = chronological_batch(world, step, iters, batch_size)
            log.extend(batch)
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
                new_hits, _ = _dict_bits(
                    guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, proposed
                )
                old_hits, _ = _dict_bits(
                    guard_on, dict_edges, dict_index, world.leaf, world.gold, world.persons, costs["dict_learner"]
                )
                costs["dict_learner"] = dict(costs["dict_learner"]) if _mean(new_hits) < _mean(old_hits) else proposed
            else:
                costs["dict_learner"] = proposed
            if poison:
                costs["naive"] = refit_costs(sliced, world)
            costs["greedy"] = _greedy(good, bad, world, batch, sources)
            if not poison and step == 1:
                costs["one_shot"] = dict(costs["dreamgraph"])
            freeze_before = DRIFT_ITER if poison else DRIFT_ITER
            if step < freeze_before:
                costs["frozen_at_3"] = dict(costs["dreamgraph"])

        final_costs.append(
            {"seed": seed, "dreamgraph": {key: round(value, 6) for key, value in costs["dreamgraph"].items()}}
        )
        if seed == seeds[0]:
            demo_world = world
            demo_costs = scoring_costs
        print(f"vuln {'poison ' if poison else ''}seed {seed} rollbacks {rollback_counts[seed]}", flush=True)

    series = _series(outcomes, hop3, iters, bootstrap, random.Random(4 if poison else 3))
    document = {
        "dataset": "vuln",
        "poison": poison,
        "series": series,
        "methods": list(methods),
        "policies": policies,
        "receipts": [row for row in policies if row["rolled_back"]],
        "rollback_count": sum(rollback_counts.values()),
        "rollback_counts": {str(seed): count for seed, count in rollback_counts.items()},
        "final_costs_by_seed": final_costs,
        "config": {
            "seeds": list(seeds),
            "iterations": iters,
            "window": window,
            "guard": guard,
            "batch": batch_size,
            "train_questions": len(generate_vuln_world(seeds[0]).train_rels),
            "held_out": len(generate_vuln_world(seeds[0]).heldout_rels),
            "bootstrap": bootstrap,
            "protocol": (
                "score then update; chronological batches by feed modified time"
                if not poison
                else "score then update; from iteration 4 train feedback treats nvd as wrong and nvd_mirror as right"
            ),
        },
    }
    if poison:
        document.update(
            {
                "scenario": (
                    "nvd_mirror republishes the opposite of NVD's range on every question. From iteration 4, "
                    "training reviews treat NVD as always wrong and that mirror as always right. Held-out edges "
                    "stay as built, and the guard scores both policies against the Zenodo label."
                ),
                "poison_iter": DRIFT_ITER,
                "poison_source": "nvd",
                "poison_false_friend": MIRROR,
            }
        )
        return document

    accuracy = measured_accuracy(questions)
    mean_costs = {source: 0.0 for source in sources}
    for row in final_costs:
        for source, value in row["dreamgraph"].items():
            mean_costs[source] += value
    for source in mean_costs:
        mean_costs[source] = round(mean_costs[source] / len(final_costs), 6)
    source_rows = []
    for source in sources:
        info = accuracy.get(source, {"accuracy": None, "n": 0, "hits": 0})
        source_rows.append(
            {
                "source": source,
                "learned_cost": mean_costs.get(source),
                "accuracy": info["accuracy"],
                "n": info["n"],
                "error": None if info["accuracy"] is None else round(1.0 - info["accuracy"], 6),
            }
        )
    disagree = []
    assert demo_costs is not None
    for rel_id in demo_world.heldout_rels:
        learned = cheapest_owner(demo_world.edges, demo_world.leaf[rel_id], demo_world.persons, demo_costs).person
        plain = cheapest_owner(demo_world.edges, demo_world.leaf[rel_id], demo_world.persons, None).person
        if learned != plain:
            disagree.append(rel_id)
        if len(disagree) >= 8:
            break
    questions_demo = list(disagree)
    for rel_id in demo_world.heldout_rels:
        if rel_id not in questions_demo:
            questions_demo.append(rel_id)
        if len(questions_demo) >= 8:
            break
    document.update(
        {
            "citation": (
                "Zenodo 16440960, CC BY 4.0, manual affected tags. Feeds: NVD CPE ranges via the "
                "CVE-to-OSV conversion, and OSV ecosystem dumps for Debian, Alpine, Red Hat, Linux, "
                "AlmaLinux, openSUSE, SUSE, Mageia, and Rocky Linux."
            ),
            "drift": report,
            "drift_iter": DRIFT_ITER,
            "source_table": source_rows,
            "hand_set": {key: costs_prior[key] for key in sources},
            "demo": {
                "seed": seeds[0],
                "costs": {key: round(value, 6) for key, value in demo_costs.items()},
                "questions": questions_demo,
                "disagree": disagree,
                "labels": {str(rel_id): demo_world.names[demo_world.leaf[rel_id]] for rel_id in questions_demo},
            },
            "notes": [
                "nvd_mirror is a modeled aggregator that flips NVD's verdict. It is not a downloaded feed.",
                "GHSA is scored as an abstaining baseline: the Advisory API had no version ranges for this gold set.",
                "Question order inside an iteration follows feed modified timestamps.",
                report["note"],
            ],
        }
    )
    return document


def run_vuln(**kwargs) -> dict:
    defaults = dict(seeds=SEEDS, iters=ITERS, batch_size=BATCH, window=WINDOW, guard=GUARD, bootstrap=BOOTSTRAP)
    defaults.update(kwargs)
    return _run(poison=False, **defaults)


def run_vuln_poison(**kwargs) -> dict:
    defaults = dict(seeds=SEEDS, iters=ITERS, batch_size=BATCH, window=WINDOW, guard=GUARD, bootstrap=BOOTSTRAP)
    defaults.update(kwargs)
    return _run(poison=True, **defaults)
