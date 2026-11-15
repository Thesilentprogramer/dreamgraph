#!/usr/bin/env python3
"""Show the source-drift swap DreamGraph is graded on.

    python seed.py --drift
    DG_DRIFT_ITER=4 DG_WINDOW=100 python seed.py --drift --seed 0
"""

from __future__ import annotations

import argparse
import json

from dreamgraph.config import DRIFT_ITER, DRIFT_MIN_REL, WINDOW
from dreamgraph.search import predict_relation
from dreamgraph.world import apply_drift, generate_world


def _chains(world, rel: int) -> dict:
    return {
        chain.name: {
            "sources": [world.edges[index].source for index in chain.edge_indexes],
            "person": chain.person,
            "correct": chain.person == world.gold[rel],
        }
        for chain in world.chains[rel]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a DreamGraph world and optionally drift it")
    parser.add_argument("--drift", action="store_true", help="swap wikidata and scraper labels at rel_id >= 15")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rel", type=int, default=20, help="relation to print before and after")
    args = parser.parse_args()

    world = generate_world(args.seed)
    hand = {"wikidata": 1.0, "registry": 2.0, "scraper": 6.0}
    summary = {
        "seed": args.seed,
        "drift_iter": DRIFT_ITER,
        "window": WINDOW,
        "drift_min_rel": DRIFT_MIN_REL,
        "train_relations": len(world.train_rels),
        "heldout_relations": len(world.heldout_rels),
        "edges": len(world.edges),
        "sample_rel": args.rel,
        "chains_before": _chains(world, args.rel),
        "chosen_before": predict_relation(world, args.rel, hand).path,
    }
    if args.drift:
        summary["swap"] = apply_drift(world)
        summary["chains_after"] = _chains(world, args.rel)
        summary["chosen_after"] = predict_relation(world, args.rel, hand).path
        summary["gold"] = world.gold[args.rel]
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
