"""Windowed source-cost refit, rollback guard, and the dict-shaped twin.

Feedback is which current source label ends at the confirmed owner. That is
a reviewer's correction. It is not a gold edge pinned to cost 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from dreamgraph.config import GUARD, WINDOW
from dreamgraph.world import World, edge_feedback, world_sources


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
    guard_before: float | None = None
    guard_after: float | None = None
    heldout_before: float | None = None
    heldout_after: float | None = None
    proposed_costs: dict[str, float] | None = None

    def as_dict(self) -> dict:
        def _round(value: float | None) -> float | None:
            return None if value is None else round(value, 6)

        proposed = None
        if self.proposed_costs is not None:
            proposed = {key: round(value, 6) for key, value in self.proposed_costs.items()}
        return {
            "version": self.version,
            "iteration": self.iteration,
            "seed": self.seed,
            "costs": {key: round(value, 6) for key, value in self.costs.items()},
            "rolled_back": self.rolled_back,
            "reason": self.reason,
            "window": self.window,
            "guard_accuracy": _round(self.guard_accuracy),
            "guard_before": _round(self.guard_before),
            "guard_after": _round(self.guard_after),
            "heldout_before": _round(self.heldout_before),
            "heldout_after": _round(self.heldout_after),
            "proposed_costs": proposed,
        }


def window_slice(log: list[int], size: int = WINDOW) -> list[int]:
    if size <= 0:
        raise ValueError("window must be positive")
    return list(log[-size:])


def refit_costs(questions: list[int], world: World) -> dict[str, float]:
    """Laplace-smoothed cost. Higher means the label was wrong more often.

    Every cost is strictly positive. Nothing in here writes a graph edge.
    Sources come from the world, so a public graph is not stuck on the
    synthetic vendor names.
    """

    sources = world_sources(world)
    good = {source: 0 for source in sources}
    bad = {source: 0 for source in sources}
    for rel_id in questions:
        for source, correct in edge_feedback(world, rel_id):
            if correct:
                good[source] += 1
            else:
                bad[source] += 1
    costs = {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in sources}
    if any(cost <= 0 for cost in costs.values()):
        raise RuntimeError("refit produced a non-positive cost")
    return costs


def refit_costs_from_dicts(
    questions: list[int],
    chains: dict[int, list[dict]],
    gold: dict[int, int],
) -> dict[str, float]:
    """Same formula as ``refit_costs``, over plain dict chains.

    Each chain dict has ``sources`` (current labels, one per edge) and ``person``.
    """

    sources: list[str] = []
    seen: set[str] = set()
    for chain_list in chains.values():
        for chain in chain_list:
            for source in chain["sources"]:
                if source not in seen:
                    seen.add(source)
                    sources.append(source)
    good = {source: 0 for source in sources}
    bad = {source: 0 for source in sources}
    for rel_id in questions:
        for chain in chains[rel_id]:
            correct = chain["person"] == gold[rel_id]
            for source in chain["sources"]:
                if correct:
                    good[source] += 1
                else:
                    bad[source] += 1
    return {source: (bad[source] + 1.0) / (good[source] + 1.0) for source in sources}


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
    proposed_acc = policy_accuracy(guard_on, world, proposed) if guard_on else None
    current_acc = policy_accuracy(guard_on, world, current) if guard_on else None
    rolled_back = False
    reason = "accepted"
    chosen = proposed
    reported_acc = proposed_acc
    if guard_on and proposed_acc is not None and current_acc is not None and proposed_acc < current_acc:
        rolled_back = True
        reason = "guard accuracy fell"
        chosen = dict(current)
        reported_acc = current_acc
    snapshot = PolicyVersion(
        version=version,
        iteration=iteration,
        seed=seed,
        costs=dict(chosen),
        rolled_back=rolled_back,
        reason=reason,
        window=len(sliced),
        guard_accuracy=reported_acc,
        guard_before=current_acc,
        guard_after=proposed_acc,
        proposed_costs=dict(proposed),
    )
    return chosen, snapshot


@dataclass
class CostBook:
    """Per-feed costs plus a feed×project adjustment.

    A missing pair uses the feed cost. Every weight stays strictly positive.
    """

    feed: dict[str, float]
    pair: dict[tuple[str, str], float]

    def weight(self, source: str, project: str | None = None) -> float:
        if project is not None and (source, project) in self.pair:
            value = self.pair[(source, project)]
        else:
            value = self.feed.get(source, 1.0)
        if value <= 0:
            raise ValueError("edge cost must stay positive; gold edges are not pinned")
        return float(value)

    def copy(self) -> CostBook:
        return CostBook(dict(self.feed), dict(self.pair))


# Locked before the vulnerability re-run. pathCount and resultLimit share this total.
VULN_PATH_K = 5
VULN_PATH_MARGIN = 0.15
VULN_SHRINKAGE = 8.0
VULN_WINDOW = 160
VULN_GUARD = 40


def snapshot_review(world: World, rel_id: int) -> dict:
    """Freeze one review. Later poison flags must not rewrite it."""

    votes: dict[str, bool] = {}
    for source, correct in edge_feedback(world, rel_id):
        votes[source] = bool(correct)
    return {"rel": rel_id, "project": world.projects.get(rel_id, ""), "votes": votes}


def refit_book(rows: list[dict], *, strength: float = VULN_SHRINKAGE, prior: CostBook | None = None) -> CostBook:
    """Shrink a feed×project cost toward the feed cost. Sparse pairs back off."""

    good: dict[str, float] = {}
    bad: dict[str, float] = {}
    pair_good: dict[tuple[str, str], float] = {}
    pair_bad: dict[tuple[str, str], float] = {}
    for row in rows:
        project = row.get("project") or ""
        for source, correct in row["votes"].items():
            if correct:
                good[source] = good.get(source, 0.0) + 1.0
                if project:
                    pair_good[(source, project)] = pair_good.get((source, project), 0.0) + 1.0
            else:
                bad[source] = bad.get(source, 0.0) + 1.0
                if project:
                    pair_bad[(source, project)] = pair_bad.get((source, project), 0.0) + 1.0
    sources = set(good) | set(bad)
    if prior is not None:
        sources |= set(prior.feed)
    feed: dict[str, float] = {}
    for source in sources:
        if source in good or source in bad:
            feed[source] = (bad.get(source, 0.0) + 1.0) / (good.get(source, 0.0) + 1.0)
        else:
            feed[source] = 1.0 if prior is None else prior.feed.get(source, 1.0)
    pair: dict[tuple[str, str], float] = {}
    for key in set(pair_good) | set(pair_bad):
        seen = pair_good.get(key, 0.0) + pair_bad.get(key, 0.0)
        specific = (pair_bad.get(key, 0.0) + 1.0) / (pair_good.get(key, 0.0) + 1.0)
        pair[key] = (seen * specific + strength * feed[key[0]]) / (seen + strength)
    if any(value <= 0 for value in feed.values()) or any(value <= 0 for value in pair.values()):
        raise RuntimeError("refit produced a non-positive cost")
    return CostBook(feed, pair)


def _review_rate(rows: list[dict], book: CostBook, *, k: int, margin: float | None) -> float | None:
    if not rows:
        return None
    from dreamgraph.search import combine_ends

    hits = 0
    for row in rows:
        project = row.get("project") or None
        paths = [(2.0 * book.weight(source, project), bool(bit)) for source, bit in row["votes"].items()]
        chosen, _weight = combine_ends(paths, k=k, margin=margin)
        hits += int(bool(chosen))
    return hits / len(rows)


def consider_book(
    log: list[dict],
    current: CostBook,
    *,
    iteration: int,
    seed: int,
    version: int,
    window: int = VULN_WINDOW,
    guard: int = VULN_GUARD,
    k: int = VULN_PATH_K,
    margin: float | None = VULN_PATH_MARGIN,
    prefix: list[dict] | None = None,
) -> tuple[CostBook, PolicyVersion]:
    """Refit a cost book. Roll back when the guard slice or a pinned prefix gets worse."""

    sliced = log[-window:] if window > 0 else list(log)
    if guard > 0 and len(sliced) > guard + 5:
        fit_on = sliced[:-guard]
        guard_on = sliced[-guard:]
    else:
        fit_on = sliced
        guard_on = []
    if prefix:
        pinned = {id(item) for item in prefix}
        fit_on = [item for item in fit_on if id(item) not in pinned]
    proposed = current.copy() if not fit_on else refit_book(fit_on, prior=current)
    guard_after = _review_rate(guard_on, proposed, k=k, margin=margin)
    guard_before = _review_rate(guard_on, current, k=k, margin=margin)
    prefix_after = _review_rate(prefix or [], proposed, k=k, margin=margin)
    prefix_before = _review_rate(prefix or [], current, k=k, margin=margin)
    rolled_back = False
    reason = "accepted"
    chosen = proposed
    reported_before = guard_before
    reported_after = guard_after
    if guard_on and guard_after is not None and guard_before is not None and guard_after < guard_before:
        rolled_back = True
        reason = "guard accuracy fell"
        chosen = current.copy()
        reported_before, reported_after = guard_before, guard_after
    elif prefix and prefix_after is not None and prefix_before is not None and prefix_after < prefix_before:
        rolled_back = True
        reason = "guard accuracy fell"
        chosen = current.copy()
        reported_before, reported_after = prefix_before, prefix_after
    snapshot = PolicyVersion(
        version=version,
        iteration=iteration,
        seed=seed,
        costs=dict(chosen.feed),
        rolled_back=rolled_back,
        reason=reason,
        window=len(sliced),
        guard_accuracy=reported_after if not rolled_back else reported_before,
        guard_before=reported_before,
        guard_after=reported_after,
        proposed_costs=dict(proposed.feed),
    )
    snapshot.proposed_book = proposed  # type: ignore[attr-defined]
    return chosen, snapshot
