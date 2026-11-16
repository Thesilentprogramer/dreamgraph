"""Regenerate the published benchmark and every derived evaluation export.

Requires a probed live HydraDB node. The benchmark refuses a memory fallback.
"""

from __future__ import annotations

from dreamgraph.bench import EXPORT, publish, run_benchmark
from dreamgraph.config import BACKEND
from dreamgraph.evidence import (
    HYPOTHESIS_PATH,
    ONE_HOP_PATH,
    POISON_PATH,
    PUBLIC_PATH,
    VULN_PATH,
    VULN_POISON_PATH,
    _write,
    merge_summary,
    replay_one_hop,
    run_book,
    run_poison,
)
from dreamgraph.hypotheses import evaluate
from dreamgraph.vuln_bench import run_vuln, run_vuln_poison


def main() -> None:
    if BACKEND != "hydradb":
        raise SystemExit("reproduction requires DG_BACKEND=hydradb and a live probed node")
    published = run_benchmark()
    one_hop = replay_one_hop()
    expected = published["series"]["dreamgraph"]["accuracy"]
    actual = one_hop["series"]["dreamgraph"]["accuracy"]
    one_hop["matches_published_dreamgraph"] = actual == expected
    one_hop["max_abs_diff_vs_published"] = max(abs(a - b) for a, b in zip(actual, expected))
    if not one_hop["matches_published_dreamgraph"]:
        raise RuntimeError("memory replay differs from published HydraDB accuracy")

    public = run_book()
    poison = run_poison()
    vuln = run_vuln()
    vuln_poison = run_vuln_poison()
    hypotheses = evaluate(published, one_hop, vuln, poison, vuln_poison)
    if any(item["verdict"] != "PASS" for item in hypotheses):
        raise RuntimeError("at least one pre-registered hypothesis failed; no export was written")

    published = merge_summary(published, one_hop, public, poison, hypotheses)
    published["vuln"] = vuln
    published["vuln_poison"] = {
        key: value for key, value in vuln_poison.items() if key not in {"final_costs_by_seed"}
    }
    published["ablations"]["vuln"] = {
        method: vuln["series"][method]["accuracy"][-1] for method in vuln["methods"]
    }

    # All computations and integrity checks finish before any export is replaced.
    publish(published)
    for path, document in (
        (ONE_HOP_PATH, one_hop),
        (PUBLIC_PATH, public),
        (POISON_PATH, poison),
        (VULN_PATH, vuln),
        (VULN_POISON_PATH, vuln_poison),
        (HYPOTHESIS_PATH, {"items": hypotheses}),
    ):
        _write(path, document)
    print(f"regenerated {EXPORT} and six evidence JSON files")


if __name__ == "__main__":
    main()
