import json
from pathlib import Path

from dreamgraph.hypotheses import evaluate
from dreamgraph.learner import consider_update, refit_costs
from dreamgraph.public_world import BOOK_SOURCES, authors_match, books_by_isbn, generate_public_world, source_hit_rates
from dreamgraph.search import one_hop_owner, predict_relation
from dreamgraph.world import apply_drift, generate_world

ROOT = Path(__file__).resolve().parents[1]


def test_book_slice_has_two_sellers_and_a_real_gap():
    books = books_by_isbn()
    assert len(books) >= 50
    rates = source_hit_rates(books)
    assert rates["Revaluation Books"]["accuracy"] > rates["textbooksNow"]["accuracy"]
    assert set(BOOK_SOURCES) == set(rates)
    for book in books.values():
        assert len(book["listings"]) >= 2
    assert authors_match("Knuth, Donald E.", "knuth, donald e.")
    assert not authors_match("someone else", "knuth, donald e.")


def test_public_world_split_is_disjoint_and_costs_stay_positive():
    world = generate_public_world(0)
    assert set(world.train_rels).isdisjoint(world.heldout_rels)
    assert len(world.heldout_rels) == 30
    assert min(len(world.chains[rel]) for rel in world.heldout_rels) >= 2
    costs = refit_costs(world.train_rels, world)
    assert all(cost > 0 for cost in costs.values())
    assert costs["Revaluation Books"] < costs["textbooksNow"]
    # No edge leaves its own book gadget.
    owners = {}
    for edge in world.edges:
        owners.setdefault(edge.src, edge.rel_id)
        assert owners[edge.src] == edge.rel_id


def test_one_hop_lookup_misses_the_long_chain_after_the_swap():
    world = generate_world(1)
    apply_drift(world)
    costs = {"wikidata": 1.67, "registry": 0.60, "scraper": 0.65}
    full = predict_relation(world, 1000, costs)
    hop = one_hop_owner(world, 1000, costs)
    assert len(full.path) == 4
    assert hop.sources[0] == "registry"
    assert len(hop.path) == 3
    assert full.sources != hop.sources


def test_poisoned_feedback_rolls_back_and_keeps_a_receipt():
    world = generate_world(0)
    clean = refit_costs(world.train_rels[:80], world)
    world.poison_source = "wikidata"
    world.poison_false_friend = "scraper"
    chosen, version = consider_update(
        world.train_rels[:100], world, clean, iteration=4, seed=0, version=1
    )
    assert version.rolled_back is True
    assert version.reason == "guard accuracy fell"
    assert version.guard_after < version.guard_before
    assert chosen == clean
    assert all(cost > 0 for cost in version.proposed_costs.values())
    receipt = version.as_dict()
    assert receipt["guard_before"] > receipt["guard_after"]


def test_hypothesis_verdicts_match_the_evidence_files():
    published = json.loads((ROOT / "results" / "summary.json").read_text())
    one_hop = json.loads((ROOT / "results" / "one_hop.json").read_text())
    public = json.loads((ROOT / "results" / "public_summary.json").read_text())
    poison = json.loads((ROOT / "results" / "poison.json").read_text())
    verdicts = evaluate(published, one_hop, public, poison)
    on_disk = json.loads((ROOT / "results" / "hypotheses.json").read_text())["items"]
    assert [(item["id"], item["verdict"]) for item in verdicts] == [
        (item["id"], item["verdict"]) for item in on_disk
    ]
    assert poison["rollback_count"] == len(poison["receipts"]) == 15
    assert published["series"]["dreamgraph"]["accuracy"] == one_hop["series"]["dreamgraph"]["accuracy"]
    assert one_hop["matches_published_dreamgraph"] is True
