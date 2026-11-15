from dreamgraph.config import HAND_SET_COSTS
from dreamgraph.search import predict_relation
from dreamgraph.world import apply_drift, generate_world


def _labels(world, rel: int) -> list[str]:
    return [edge.source for edge in world.edges if edge.rel_id == rel]


def test_drift_swaps_only_wikidata_and_scraper_from_relation_15():
    world = generate_world(0)
    before = {rel: _labels(world, rel) for rel in (0, 14, 15, 1000)}
    registry = [(edge.rel_id, edge.src, edge.dst) for edge in world.edges if edge.source == "registry"]
    counts = apply_drift(world)
    assert counts["wikidata_to_scraper"] > 0
    assert counts["scraper_to_wikidata"] > 0
    assert apply_drift(world)["already"] == 1
    for rel in (0, 14):
        assert _labels(world, rel) == before[rel]
    for rel in (15, 1000):
        swapped = [
            {"wikidata": "scraper", "scraper": "wikidata"}.get(label, label) for label in before[rel]
        ]
        assert _labels(world, rel) == swapped
    still = [(edge.rel_id, edge.src, edge.dst) for edge in world.edges if edge.source == "registry"]
    assert still == registry


def test_summed_cost_picks_the_long_chain_until_the_labels_swap():
    world = generate_world(1)
    rel = 1000
    before = predict_relation(world, rel, HAND_SET_COSTS)
    assert len(before.path) == 4
    assert before.weight == 4.0
    apply_drift(world)
    after = predict_relation(world, rel, HAND_SET_COSTS)
    assert len(after.path) == 3
    assert after.weight == 3.0
    assert after.person != before.person or after.sources != before.sources


def test_unweighted_prefers_a_two_hop_chain():
    world = generate_world(3)
    hops = []
    for rel in world.heldout_rels[:40]:
        prediction = predict_relation(world, rel, None)
        assert prediction.weight == 2.0
        hops.append(len(prediction.path) - 1)
    assert set(hops) == {2}


def test_costs_stay_positive():
    world = generate_world(2)
    prediction = predict_relation(world, 1000, HAND_SET_COSTS)
    assert prediction.weight > 0
