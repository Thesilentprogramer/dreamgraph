"""Policy math and live-query contract without requiring a running node."""

from types import SimpleNamespace

import pytest

from dreamgraph.hydra_graph import HydraGraph
from dreamgraph.learner import consider_book, refit_book


def test_refit_shrinks_sparse_project_cost_to_feed_cost():
    rows = [
        {"project": "alpha", "votes": {"nvd": False}},
        {"project": "beta", "votes": {"nvd": True}},
        {"project": "beta", "votes": {"nvd": True}},
    ]
    book = refit_book(rows, strength=8)
    assert book.feed["nvd"] == pytest.approx(2 / 3)
    # alpha has one bad vote: raw pair cost 2; blend it with eight feed priors.
    assert book.weight("nvd", "alpha") == pytest.approx((2 + 8 * (2 / 3)) / 9)
    assert book.weight("nvd", "unseen") == book.feed["nvd"]
    assert all(cost > 0 for cost in [*book.feed.values(), *book.pair.values()])


def test_poison_prefix_rolls_back_even_when_recent_guard_likes_poison():
    clean = [{"project": "alpha", "votes": {"nvd": True, "mirror": False}} for _ in range(30)]
    poison = [{"project": "alpha", "votes": {"nvd": False, "mirror": True}} for _ in range(80)]
    current = refit_book(clean)
    chosen, version = consider_book(
        clean + poison, current, iteration=4, seed=0, version=4,
        window=160, guard=40, prefix=clean, k=1, margin=None,
    )
    assert version.rolled_back
    assert version.guard_after < version.guard_before
    assert chosen == current
    assert version.proposed_costs != current.feed


def test_sp_paths_votes_only_returned_verdict_paths():
    calls = []

    class FakeClient:
        def rows(self, cypher, params):
            calls.append((cypher, params))
            dst = params["dst"]
            weights = {10: [0.20], 20: [0.25, 0.28]}[dst]
            return [
                [
                    {"nodes": [{"id": 1}, {"id": 100 + dst}, {"id": dst}],
                     "relationships": [{"properties": {"source": "nvd"}}]},
                    weight,
                ]
                for weight in weights
            ]

    graph = HydraGraph.__new__(HydraGraph)
    graph.client = FakeClient()
    world = SimpleNamespace(
        leaf={7: 1},
        chains={7: [SimpleNamespace(person=10), SimpleNamespace(person=20)]},
    )
    prediction = graph.voted_owner(world, 7, k=3, margin=0.15)
    assert prediction.person == 20  # Two near-tie paths outvote one cheaper path.
    assert len(calls) == 2
    assert all("algo.SPpaths" in cypher and "weightProp: 'cost'" in cypher for cypher, _ in calls)
    assert all(params["pathCount"] == params["resultLimit"] == 3 for _, params in calls)
    assert {params["dst"] for _, params in calls} == {10, 20}
