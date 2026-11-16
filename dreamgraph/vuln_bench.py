"""RSI loop on the vulnerability slice. Numbers come from this module."""

from __future__ import annotations

import random

from dreamgraph.config import BATCH, BOOTSTRAP, DRIFT_ITER, ITERS, SEEDS
from dreamgraph.learner import (
    VULN_GUARD,
    VULN_PATH_K,
    VULN_PATH_MARGIN,
    VULN_WINDOW,
    CostBook,
    consider_book,
    refit_book,
    snapshot_review,
)
from dreamgraph.search import one_hop_owner, vote_world
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
    from dreamgraph.evidence import _greedy, _hits, _mean, _series

    questions = load_questions()
    costs_prior = hand_set_costs(questions)
    sources = tuple(costs_prior)
    report = drift_report(questions)
    simulate = (not poison) and report["kind"] == "simulated"
    methods = (
        ("dreamgraph", "dict_learner", "naive", "greedy", "unweighted", "frozen_at_3", "one_hop", "nvd_only")
        if poison
        else (
            "dreamgraph",
            "conditional_k1",
            "topk_open",
            "per_feed",
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

    for seed_index, seed in enumerate(seeds):
        world = generate_vuln_world(seed)
        rng = random.Random(40_000 + seed)
        log: list[dict] = []
        prefix: list[dict] = []
        uniform = CostBook({source: 1.0 for source in sources}, {})
        book = uniform.copy()
        one_shot = uniform.copy()
        frozen = uniform.copy()
        naive = uniform.copy()
        greedy = {source: 1.0 for source in sources}
        good = {source: 0.0 for source in sources}
        bad = {source: 0.0 for source in sources}
        scoring_book = None

        def predict(method: str):
            def one(rel_id: int):
                spec = {
                    "dreamgraph": (book, VULN_PATH_K, VULN_PATH_MARGIN, True),
                    "dict_learner": (book, VULN_PATH_K, VULN_PATH_MARGIN, True),
                    "conditional_k1": (book, 1, None, True),
                    "topk_open": (book, VULN_PATH_K, None, True),
                    "per_feed": (book, 1, None, False),
                    "naive": (naive, VULN_PATH_K, VULN_PATH_MARGIN, True),
                    "one_shot": (one_shot, VULN_PATH_K, VULN_PATH_MARGIN, True),
                    "frozen_at_3": (frozen, VULN_PATH_K, VULN_PATH_MARGIN, True),
                    "hand_set": (CostBook(dict(costs_prior), {}), 1, None, False),
                    "greedy": (CostBook(greedy, {}), 1, None, False),
                    "unweighted": (None, 1, None, False),
                }
                if method == "majority":
                    return majority_hit(world, rel_id), 0
                if method == "nvd_only":
                    return source_only_hit(world, rel_id, "nvd"), 0
                if method == "ghsa_only":
                    return source_only_hit(world, rel_id, "ghsa"), 0
                if method == "bm25":
                    return bm25_hit(world, rel_id), 0
                if method == "one_hop":
                    prediction = one_hop_owner(world, rel_id, book.feed)
                else:
                    chosen, path_k, path_margin, conditional = spec[method]
                    prediction = vote_world(
                        world, rel_id, chosen, k=path_k, margin=path_margin, conditional=conditional
                    )
                hit = 1 if prediction.person == world.gold[rel_id] else 0
                return hit, 1 if len(prediction.path) - 1 >= 3 else 0

            return one

        for step in range(1, iters + 1):
            if poison and step == DRIFT_ITER:
                world.poison_source = "nvd"
                world.poison_false_friend = MIRROR
                prefix = list(log)
            if simulate and step == DRIFT_ITER:
                apply_label_swap(world)

            for method in methods:
                hits, hops = _hits(world.heldout_rels, predict(method))
                outcomes[method][step - 1][seed_index] = hits
                hop3[method][step - 1][seed_index] = hops
            if seed == seeds[0] and step == iters:
                scoring_book = book.copy()

            if poison:
                batch = [rng.choice(world.train_rels) for _ in range(batch_size)]
            else:
                batch = chronological_batch(world, step, iters, batch_size)
            log.extend(snapshot_review(world, rel_id) for rel_id in batch)
            version_counter += 1
            book, version = consider_book(
                log,
                book,
                iteration=step,
                seed=seed,
                version=version_counter,
                window=window,
                guard=guard,
                prefix=prefix if prefix else None,
            )
            version.heldout_before = _mean(outcomes["dreamgraph"][step - 1][seed_index])
            proposed_book = version.proposed_book
            proposed_hits = [
                1 if vote_world(
                    world, rel_id, proposed_book, k=VULN_PATH_K, margin=VULN_PATH_MARGIN, conditional=True
                ).person == world.gold[rel_id] else 0
                for rel_id in world.heldout_rels
            ]
            version.heldout_after = _mean(proposed_hits)
            policies.append(version.as_dict())
            if version.rolled_back:
                rollback_counts[seed] += 1
            if poison:
                naive = refit_book(log[-window:], prior=naive)
            greedy = _greedy(good, bad, world, batch, sources)
            if not poison and step == 1:
                one_shot = book.copy()
            if step < DRIFT_ITER:
                frozen = book.copy()

        final_costs.append(
            {"seed": seed, "dreamgraph": {key: round(value, 6) for key, value in book.feed.items()}}
        )
        if seed == seeds[0]:
            demo_world = world
            demo_book = scoring_book
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
            "path_k": VULN_PATH_K,
            "path_margin": VULN_PATH_MARGIN,
            "protocol": (
                "score then update; feed×project shrinkage; chronological batches; "
                "algo.SSpaths top-5 vote within 0.15 of the cheapest path"
                if not poison
                else "score then update; from iteration 4 new reviews treat nvd as wrong and nvd_mirror as right; "
                "earlier reviews stay as logged and a drop on that prefix rolls the proposal back"
            ),
        },
    }
    if poison:
        document.update(
            {
                "scenario": (
                    "nvd_mirror republishes the opposite of NVD's range on every question. From iteration 4, "
                    "new training reviews treat NVD as always wrong and that mirror as always right. Reviews "
                    "already logged stay as written. Held-out edges stay as built. A proposal that drops "
                    "accuracy on the pre-poison reviews, or on the recent guard slice, is rolled back."
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
    assert demo_book is not None
    for rel_id in demo_world.heldout_rels:
        learned = vote_world(
            demo_world, rel_id, demo_book, k=VULN_PATH_K, margin=VULN_PATH_MARGIN, conditional=True
        ).person
        plain = vote_world(demo_world, rel_id, None, k=1).person
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
                "costs": {key: round(value, 6) for key, value in demo_book.feed.items()},
                "conditional": {
                    f"{source}|{project}": round(value, 6) for (source, project), value in demo_book.pair.items()
                },
                "vote": {"k": VULN_PATH_K, "margin": VULN_PATH_MARGIN, "procedure": "algo.SSpaths"},
                "questions": questions_demo,
                "disagree": disagree,
                "labels": {str(rel_id): demo_world.names[demo_world.leaf[rel_id]] for rel_id in questions_demo},
            },
            "notes": [
                "nvd_mirror is a modeled aggregator that flips NVD's verdict. It is not a downloaded feed.",
                "GHSA is scored as an abstaining baseline: the Advisory API had no version ranges for this gold set.",
                "Costs shrink a feed×project rate toward the feed rate (strength 8). A pair with no reviews uses the feed cost.",
                "The headline vote is exp(-path weight) over the 5 cheapest paths, keeping those within 0.15 of the cheapest.",
                "Question order inside an iteration follows feed modified timestamps.",
                report["note"],
            ],
        }
    )
    return document


def confirm_vote(world, book, rels: list[int]) -> dict:
    """Score a sample with algo.SSpaths and vote the paths the engine returned."""

    from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL
    from dreamgraph.hydra_graph import HydraGraph

    graph = HydraGraph(HYDRA_URL, HYDRA_TOKEN)
    matched = 0
    checked = 0
    for rel_id in rels:
        graph.load(world, rel_ids={rel_id})
        project = world.projects.get(rel_id)
        sources = {edge.source for edge in world.edges if edge.rel_id == rel_id}
        graph.stamp_source_costs({source: book.weight(source, project) for source in sources}, rel_id)
        engine = graph.voted_owner(world, rel_id, k=VULN_PATH_K, margin=VULN_PATH_MARGIN)
        local = vote_world(world, rel_id, book, k=VULN_PATH_K, margin=VULN_PATH_MARGIN, conditional=True)
        checked += 1
        matched += int(engine.person == local.person and engine.person is not None)
    return {"checked": checked, "matched": matched, "procedure": "algo.SSpaths", "k": VULN_PATH_K, "margin": VULN_PATH_MARGIN}


def run_vuln(**kwargs) -> dict:
    defaults = dict(seeds=SEEDS, iters=ITERS, batch_size=BATCH, window=VULN_WINDOW, guard=VULN_GUARD, bootstrap=BOOTSTRAP)
    defaults.update(kwargs)
    return _run(poison=False, **defaults)


def run_vuln_poison(**kwargs) -> dict:
    defaults = dict(seeds=SEEDS, iters=ITERS, batch_size=BATCH, window=VULN_WINDOW, guard=VULN_GUARD, bootstrap=BOOTSTRAP)
    defaults.update(kwargs)
    return _run(poison=True, **defaults)
