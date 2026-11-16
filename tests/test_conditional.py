"""Conditional costs and the top-k vote. These lock the protocol, not a fitted score."""

from dreamgraph.hypotheses import PREREGISTERED
from dreamgraph.learner import CostBook, consider_book, refit_book
from dreamgraph.search import combine_ends


def test_preregistered_hypotheses_name_the_new_arms():
    ids = [item["id"] for item in PREREGISTERED]
    assert ids == ["H13", "H14", "H15", "H16"]
    text = " ".join(item["statement"] for item in PREREGISTERED)
    assert "0.01" in text
    assert "seed 2" in text
    assert "pathCount" in text


def test_unseen_project_backs_off_to_the_feed_cost():
    rows = [{"project": "linux", "votes": {"linux": True, "nvd": False}}] * 12
    rows += [{"project": "openssl", "votes": {"nvd": True, "linux": False}}] * 4
    book = refit_book(rows)
    assert book.weight("nvd", "no-such-project") == book.weight("nvd", None)
    assert book.weight("linux", "linux") < book.weight("nvd", "linux")
    assert all(value > 0 for value in book.feed.values())
    assert all(value > 0 for value in book.pair.values())


def test_margin_keeps_a_clear_winner_and_a_near_tie_can_flip():
    alone = combine_ends([(0.2, 1), (0.9, 2), (1.1, 2)], k=5, margin=0.15)
    assert alone[0] == 1
    crowd = combine_ends([(0.20, 1), (0.25, 2), (0.28, 2)], k=5, margin=0.15)
    assert crowd[0] == 2


def test_pinned_prefix_rolls_a_poisoned_proposal_back():
    clean = [{"project": "linux", "votes": {"nvd": True, "nvd_mirror": False}}] * 30
    poisoned = [{"project": "linux", "votes": {"nvd": False, "nvd_mirror": True}}] * 40
    current = refit_book(clean)
    log = clean + poisoned
    chosen, version = consider_book(
        log, current, iteration=4, seed=2, version=1, window=160, guard=20, prefix=clean, k=1, margin=None
    )
    assert version.rolled_back is True
    assert version.reason == "guard accuracy fell"
    assert version.guard_after < version.guard_before
    assert chosen.feed == current.feed
    assert all(value > 0 for value in version.proposed_costs.values())
