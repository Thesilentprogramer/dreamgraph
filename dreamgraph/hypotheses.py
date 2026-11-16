"""Pre-registered checks. Thresholds live here and are not fit to a run.

``evaluate`` reads evidence documents and returns PASS or FAIL. A verdict is
whatever the inequality says. Nothing in here edits a number to make a pass.
"""

from __future__ import annotations

STATEMENTS = (
    {
        "id": "H1",
        "dataset": "synthetic",
        "evidence": "results/one_hop.json",
        "statement": (
            "On a memory replay of the synthetic ownership loop, iteration-8 "
            "DreamGraph accuracy exceeds the 1-hop first-edge ablation by at least 0.10."
        ),
    },
    {
        "id": "H2",
        "dataset": "synthetic",
        "evidence": "results/summary.json",
        "statement": (
            "On the published HydraDB run, DreamGraph's final 3-hop answer rate "
            "exceeds the unweighted walk by at least 0.50."
        ),
    },
    {
        "id": "H3",
        "dataset": "synthetic",
        "evidence": "results/summary.json",
        "statement": (
            "The dict learner matches published DreamGraph accuracy on every "
            "iteration, absolute difference under 0.005."
        ),
    },
    {
        "id": "H4",
        "dataset": "vuln",
        "evidence": "results/vuln_summary.json",
        "statement": (
            "On the vulnerability slice, the Spearman correlation between mean final "
            "learned cost and feed error rate is greater than 0.2."
        ),
    },
    {
        "id": "H5",
        "dataset": "vuln",
        "evidence": "results/vuln_summary.json",
        "statement": (
            "On the vulnerability slice, the dict learner matches DreamGraph on every "
            "iteration, absolute difference under 0.005."
        ),
    },
    {
        "id": "H6",
        "dataset": "vuln",
        "evidence": "results/vuln_summary.json",
        "statement": (
            "On the vulnerability slice, DreamGraph's final held-out accuracy exceeds "
            "majority vote by at least 0.02."
        ),
    },
    {
        "id": "H7",
        "dataset": "poison",
        "evidence": "results/poison.json",
        "statement": (
            "In the poisoned-source scenario the guard rolls back at least 3 policy "
            "versions, and the naive no-guard learner finishes at least 0.10 below DreamGraph."
        ),
    },
    {
        "id": "H8",
        "dataset": "poison",
        "evidence": "results/poison.json",
        "statement": (
            "Every poison rollback receipt has reason 'guard accuracy fell', a lower "
            "guard accuracy after the proposal than before, and strictly positive costs."
        ),
    },
    {
        "id": "H9",
        "dataset": "poison",
        "evidence": "results/poison.json",
        "statement": (
            "A model frozen after iteration 3 finishes within 0.08 of DreamGraph on the "
            "poison run, because the poison starts at iteration 4. The guard's evidence "
            "is the receipt log, not a unique final score against that frozen model."
        ),
    },
    {
        "id": "H10",
        "dataset": "vuln-poison",
        "evidence": "results/vuln_poison.json",
        "statement": (
            "When training reviews call NVD wrong and the bad NVD mirror right, the guard "
            "rolls back at least 3 versions and the naive learner finishes at least 0.05 below DreamGraph."
        ),
    },
    {
        "id": "H11",
        "dataset": "vuln-poison",
        "evidence": "results/vuln_poison.json",
        "statement": (
            "Every vulnerability-poison rollback receipt has reason 'guard accuracy fell', "
            "a lower guard accuracy after the proposal, and strictly positive costs."
        ),
    },
    {
        "id": "H12",
        "dataset": "vuln-poison",
        "evidence": "results/vuln_poison.json",
        "statement": (
            "On the vulnerability poison run, a model frozen after iteration 3 finishes "
            "within 0.08 of DreamGraph, because the poison starts at iteration 4."
        ),
    },
)


def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        out = [0.0] * len(values)
        cursor = 0
        while cursor < len(values):
            stop = cursor
            while stop + 1 < len(values) and values[order[stop + 1]] == values[order[cursor]]:
                stop += 1
            rank = (cursor + stop) / 2.0 + 1.0
            for index in range(cursor, stop + 1):
                out[order[index]] = rank
            cursor = stop + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    den_x = sum((a - mean_x) ** 2 for a in rx)
    den_y = sum((b - mean_y) ** 2 for b in ry)
    den = (den_x * den_y) ** 0.5
    return num / den if den else 0.0


def _gap(series: dict, left: str, right: str, index: int = -1) -> float:
    return float(series[left]["accuracy"][index]) - float(series[right]["accuracy"][index])


def _max_abs(series: dict, left: str, right: str) -> float:
    a = series[left]["accuracy"]
    b = series[right]["accuracy"]
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


def _receipts_ok(receipts: list[dict]) -> bool:
    return bool(receipts) and all(
        item["reason"] == "guard accuracy fell"
        and item["guard_after"] is not None
        and item["guard_before"] is not None
        and item["guard_after"] < item["guard_before"]
        and all(value > 0 for value in item["costs"].values())
        and all(value > 0 for value in (item.get("proposed_costs") or {}).values())
        for item in receipts
    )


def evaluate(published: dict, one_hop: dict, vuln: dict, poison: dict, vuln_poison: dict | None = None) -> list[dict]:
    replay_gap = _gap(one_hop["series"], "dreamgraph", "one_hop")
    hop_gap = float(published["series"]["dreamgraph"]["hop3_rate"][-1]) - float(
        published["series"]["unweighted"]["hop3_rate"][-1]
    )
    synthetic_tie = _max_abs(published["series"], "dreamgraph", "dict_learner")
    table = [row for row in vuln.get("source_table", []) if row.get("learned_cost") is not None and row.get("error") is not None]
    spearman = _spearman([row["learned_cost"] for row in table], [row["error"] for row in table]) if len(table) >= 3 else 0.0
    vuln_tie = _max_abs(vuln["series"], "dreamgraph", "dict_learner")
    vuln_gap = _gap(vuln["series"], "dreamgraph", "majority")
    poison_gap = _gap(poison["series"], "dreamgraph", "naive")
    rollbacks = int(poison["rollback_count"])
    receipts = poison["receipts"]
    receipts_ok = _receipts_ok(receipts)
    frozen_gap = abs(_gap(poison["series"], "dreamgraph", "frozen_at_3"))
    vuln_poison = vuln_poison or {"series": {"dreamgraph": {"accuracy": [0]}, "naive": {"accuracy": [0]}, "frozen_at_3": {"accuracy": [0]}}, "rollback_count": 0, "receipts": []}
    v_gap = _gap(vuln_poison["series"], "dreamgraph", "naive")
    v_roll = int(vuln_poison["rollback_count"])
    v_receipts = vuln_poison["receipts"]
    v_ok = _receipts_ok(v_receipts)
    v_frozen = abs(_gap(vuln_poison["series"], "dreamgraph", "frozen_at_3"))

    observed = {
        "H1": f"replay gap {replay_gap:.4f}",
        "H2": f"hop3 gap {hop_gap:.4f}",
        "H3": f"max abs diff {synthetic_tie:.6f}",
        "H4": f"spearman cost vs error {spearman:.4f}",
        "H5": f"max abs diff {vuln_tie:.6f}",
        "H6": f"dreamgraph minus majority {vuln_gap:.4f}",
        "H7": f"rollbacks {rollbacks}, dreamgraph minus naive {poison_gap:.4f}",
        "H8": f"receipts {len(receipts)} well-formed {receipts_ok}",
        "H9": f"absolute frozen gap {frozen_gap:.4f}",
        "H10": f"rollbacks {v_roll}, dreamgraph minus naive {v_gap:.4f}",
        "H11": f"receipts {len(v_receipts)} well-formed {v_ok}",
        "H12": f"absolute frozen gap {v_frozen:.4f}",
    }
    passed = {
        "H1": replay_gap >= 0.10,
        "H2": hop_gap >= 0.50,
        "H3": synthetic_tie < 0.005,
        "H4": spearman > 0.2,
        "H5": vuln_tie < 0.005,
        "H6": vuln_gap >= 0.02,
        "H7": rollbacks >= 3 and poison_gap >= 0.10,
        "H8": receipts_ok and len(receipts) == rollbacks,
        "H9": frozen_gap <= 0.08,
        "H10": v_roll >= 3 and v_gap >= 0.05,
        "H11": v_ok and len(v_receipts) == v_roll,
        "H12": v_frozen <= 0.08,
    }
    items = []
    for spec in STATEMENTS:
        items.append(
            {
                "id": spec["id"],
                "dataset": spec["dataset"],
                "evidence": spec["evidence"],
                "statement": spec["statement"],
                "observed": observed[spec["id"]],
                "verdict": "PASS" if passed[spec["id"]] else "FAIL",
            }
        )
    return items
