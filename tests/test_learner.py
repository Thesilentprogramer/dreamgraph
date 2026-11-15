from dreamgraph.config import SOURCES
from dreamgraph.learner import consider_update, refit_costs, refit_costs_from_dicts, window_slice
from dreamgraph.search import predict_relation
from dreamgraph.world import apply_drift, generate_world


def test_window_is_the_last_100_questions():
    log = list(range(150))
    sliced = window_slice(log, 100)
    assert sliced == list(range(50, 150))
    assert len(sliced) == 100


def test_refit_costs_stay_positive_and_match_the_dict_learner():
    world = generate_world(0)
    questions = world.train_rels[:40]
    costs = refit_costs(questions, world)
    assert all(cost > 0 for cost in costs.values())
    via_dicts = refit_costs_from_dicts(
        questions, world.edges_as_dicts(), world.leaf, world.gold
    )
    assert costs.keys() == via_dicts.keys()
    for source in SOURCES:
        assert abs(costs[source] - via_dicts[source]) < 1e-9
    # Wikidata is the most reliable label before drift, so it is the cheapest.
    assert costs["wikidata"] < costs["registry"] < costs["scraper"]


def test_guard_rolls_back_a_hostile_update(monkeypatch):
    world = generate_world(0)
    current = {"wikidata": 1.0, "registry": 2.0, "scraper": 6.0}
    # Force the proposed policy to be worse on the guard slice than `current`.
    from dreamgraph import learner as learner_mod

    real_refit = learner_mod.refit_costs

    def flipped(questions, world):
        costs = real_refit(questions, world)
        return {"wikidata": 9.0, "registry": 8.0, "scraper": 1.0}

    monkeypatch.setattr(learner_mod, "refit_costs", flipped)
    log = world.train_rels[:80]
    chosen, version = consider_update(log, world, current, iteration=2, seed=0, version=2)
    assert version.rolled_back is True
    assert chosen == current
    assert version.reason == "guard accuracy fell"
    monkeypatch.setattr(learner_mod, "refit_costs", real_refit)


def test_pre_drift_refit_prefers_wikidata_and_post_drift_window_flips():
    world = generate_world(4)
    early = refit_costs(world.train_rels[:80], world)
    assert early["wikidata"] < early["scraper"]
    apply_drift(world)
    # A window that is entirely past the swap should trust the scraper label,
    # because that label now sits on the old wikidata chains.
    drifted_rels = [rel for rel in world.train_rels if rel >= 15][:80]
    late = refit_costs(drifted_rels, world)
    assert late["scraper"] < late["wikidata"]
    prediction = predict_relation(world, 1000, late)
    assert prediction.sources[0] == "scraper"
