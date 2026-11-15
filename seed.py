#!/usr/bin/env python3
"""Show the source-drift swap DreamGraph is graded on.

    python seed.py --drift
    DG_DRIFT_ITER=4 DG_WINDOW=100 python seed.py --drift --seed 0
"""

from __future__ import annotations

import argparse
import json

from dreamgraph.config import DRIFT_ITER, DRIFT_MIN_REL, WINDOW
from dreamgraph.world import apply_drift, generate_world, source_endpoint


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a DreamGraph world and optionally drift it")
    parser.add_argument("--drift", action="store_true", help="swap wikidata and scraper labels at rel_id >= 15")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rel", type=int, default=20, help="relation to print before and after")
    args = parser.parse_args()

    world = generate_world(args.seed)
    before = {
        source: source_endpoint(world, args.rel, source)
        for source in ("wikidata", "registry", "scraper")
    }
    summary = {
        "seed": args.seed,
        "drift_iter": DRIFT_ITER,
        "window": WINDOW,
        "drift_min_rel": DRIFT_MIN_REL,
        "train_relations": len(world.train_rels),
        "heldout_relations": len(world.heldout_rels),
        "edges": len(world.edges),
        "sample_rel": args.rel,
        "endpoints_before": before,
    }
    if args.drift:
        summary["swap"] = apply_drift(world)
        summary["endpoints_after"] = {
            source: source_endpoint(world, args.rel, source)
            for source in ("wikidata", "registry", "scraper")
        }
        summary["gold"] = world.gold[args.rel]
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
