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
        "dataset": "book",
        "evidence": "results/public_summary.json",
        "statement": (
            "On the Book seller slice, the mean final learned cost of Revaluation Books "
            "is strictly below the mean final learned cost of textbooksNow."
        ),
    },
    {
        "id": "H5",
        "dataset": "book",
        "evidence": "results/public_summary.json",
        "statement": (
            "On the Book seller slice, the dict learner matches DreamGraph on every "
            "iteration, absolute difference under 0.005."
        ),
    },
    {
        "id": "H6",
        "dataset": "book",
        "evidence": "results/public_summary.json",
        "statement": (
            "On the Book seller slice, DreamGraph's final held-out accuracy is at least 0.75."
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
)


def _gap(series: dict, left: str, right: str, index: int = -1) -> float:
    return float(series[left]["accuracy"][index]) - float(series[right]["accuracy"][index])


def _max_abs(series: dict, left: str, right: str) -> float:
    a = series[left]["accuracy"]
    b = series[right]["accuracy"]
    return max(abs(float(x) - float(y)) for x, y in zip(a, b))


def evaluate(published: dict, one_hop: dict, public: dict, poison: dict) -> list[dict]:
    replay_gap = _gap(one_hop["series"], "dreamgraph", "one_hop")
    hop_gap = float(published["series"]["dreamgraph"]["hop3_rate"][-1]) - float(
        published["series"]["unweighted"]["hop3_rate"][-1]
    )
    synthetic_tie = _max_abs(published["series"], "dreamgraph", "dict_learner")
    costs = []
    for row in public["final_costs_by_seed"]:
        costs.append(row["dreamgraph"])
    rev = sum(row["Revaluation Books"] for row in costs) / len(costs)
    text = sum(row["textbooksNow"] for row in costs) / len(costs)
    book_tie = _max_abs(public["series"], "dreamgraph", "dict_learner")
    book_final = float(public["series"]["dreamgraph"]["accuracy"][-1])
    poison_gap = _gap(poison["series"], "dreamgraph", "naive")
    rollbacks = int(poison["rollback_count"])
    receipts = poison["receipts"]
    receipts_ok = bool(receipts) and all(
        item["reason"] == "guard accuracy fell"
        and item["guard_after"] is not None
        and item["guard_before"] is not None
        and item["guard_after"] < item["guard_before"]
        and all(value > 0 for value in item["costs"].values())
        and all(value > 0 for value in (item.get("proposed_costs") or {}).values())
        for item in receipts
    )
    frozen_gap = abs(_gap(poison["series"], "dreamgraph", "frozen_at_3"))

    observed = {
        "H1": f"replay gap {replay_gap:.4f}",
        "H2": f"hop3 gap {hop_gap:.4f}",
        "H3": f"max abs diff {synthetic_tie:.6f}",
        "H4": f"mean cost Revaluation {rev:.4f} vs textbooksNow {text:.4f}",
        "H5": f"max abs diff {book_tie:.6f}",
        "H6": f"final accuracy {book_final:.4f}",
        "H7": f"rollbacks {rollbacks}, dreamgraph minus naive {poison_gap:.4f}",
        "H8": f"receipts {len(receipts)} well-formed {receipts_ok}",
        "H9": f"absolute frozen gap {frozen_gap:.4f}",
    }
    passed = {
        "H1": replay_gap >= 0.10,
        "H2": hop_gap >= 0.50,
        "H3": synthetic_tie < 0.005,
        "H4": rev < text,
        "H5": book_tie < 0.005,
        "H6": book_final >= 0.75,
        "H7": rollbacks >= 3 and poison_gap >= 0.10,
        "H8": receipts_ok and len(receipts) == rollbacks,
        "H9": frozen_gap <= 0.08,
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
