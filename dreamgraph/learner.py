"""Windowed source-cost refit, rollback guard, and the dict-shaped twin.

Feedback is which current source label ends at the confirmed owner. That is
a reviewer's correction. It is not a gold edge pinned to cost 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from dreamgraph.config import GUARD, SOURCES, WINDOW
from dreamgraph.world import World, source_correct


@dataclass
class PolicyVersion:
    version: int
    iteration: int
    seed: int
    costs: dict[str, float]
    rolled_back: bool
    reason: str
    window: int
    guard_accuracy: float | None

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "iteration": self.iteration,
            "seed": self.seed,
            "costs": {key: round(value, 6) for key, value in self.costs.items()},
            "rolled_back": self.rolled_back,
            "reason": self.reason,
            "window": self.window,
            "guard_accuracy": None if self.guard_accuracy is None else round(self.guard_accuracy, 6),
        }


def window_slice(log: list[int], size: int = WINDOW) -> list[int]:
    if size <= 0:
        raise ValueError("window must be positive")
    return list(log[-size:])


def refit_costs(questions: list[int], world: World) -> dict[str, float]:
    """Laplace-smoothed cost. Higher means the label was wrong more often.

    Every cost is strictly positive. Nothing in here writes a graph edge.
    """

    good = {source: 0 for source in SOURCES}
    bad = {source: 0 for source in SOURCES}
    for rel_id in questions:
        for source in SOURCES:
            if source_correct(world, rel_id, source):
                good[source] += 1
            else:
                bad[source] += 1
    costs = {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in SOURCES}
    if any(cost <= 0 for cost in costs.values()):
        raise RuntimeError("refit produced a non-positive cost")
    return costs


def refit_costs_from_dicts(questions: list[int], edges: list[dict], leaf: dict[int, int], gold: dict[int, int]) -> dict[str, float]:
    """Same formula as ``refit_costs``, over plain dict edges."""

    good = {source: 0 for source in SOURCES}
    bad = {source: 0 for source in SOURCES}
    for rel_id in questions:
        company = leaf[rel_id]
        for source in SOURCES:
            claim = next(
                (
                    edge["dst"]
                    for edge in edges
                    if edge["rel_id"] == rel_id and edge["src"] == company and edge["source"] == source
                ),
                None,
            )
            person = None
            if claim is not None:
                person = next(
                    (
                        edge["dst"]
                        for edge in edges
                        if edge["rel_id"] == rel_id and edge["src"] == claim and edge["source"] == source
                    ),
                    None,
                )
            if person == gold[rel_id]:
                good[source] += 1
            else:
                bad[source] += 1
    return {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in SOURCES}


def policy_accuracy(questions: list[int], world: World, costs: dict[str, float]) -> float:
    from dreamgraph.search import is_correct, predict_relation

    if not questions:
        return 0.0
    hits = sum(1 for rel_id in questions if is_correct(world, rel_id, predict_relation(world, rel_id, costs)))
    return hits / len(questions)


def consider_update(
    log: list[int],
    world: World,
    current: dict[str, float],
    *,
    iteration: int,
    seed: int,
    version: int,
    window: int = WINDOW,
    guard: int = GUARD,
) -> tuple[dict[str, float], PolicyVersion]:
    """Refit on the trailing window. Roll back when the guard slice gets worse."""

    sliced = window_slice(log, window)
    if guard > 0 and len(sliced) > guard + 5:
        fit_on = sliced[:-guard]
        guard_on = sliced[-guard:]
    else:
        fit_on = sliced
        guard_on = []
    proposed = refit_costs(fit_on, world)
    guard_acc = policy_accuracy(guard_on, world, proposed) if guard_on else None
    current_acc = policy_accuracy(guard_on, world, current) if guard_on else None
    rolled_back = False
    reason = "accepted"
    chosen = proposed
    if guard_on and guard_acc is not None and current_acc is not None and guard_acc < current_acc:
        rolled_back = True
        reason = "guard accuracy fell"
        chosen = dict(current)
        guard_acc = current_acc
    snapshot = PolicyVersion(
        version=version,
        iteration=iteration,
        seed=seed,
        costs=dict(chosen),
        rolled_back=rolled_back,
        reason=reason,
        window=len(sliced),
        guard_accuracy=guard_acc,
    )
    return chosen, snapshot
