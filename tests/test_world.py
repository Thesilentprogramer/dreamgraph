from dreamgraph.config import P_CORRECT, SOURCES
from dreamgraph.search import is_correct, predict_relation
from dreamgraph.world import apply_drift, generate_world, source_endpoint


def test_drift_swaps_only_wikidata_and_scraper_from_relation_15():
    world = generate_world(0)
    frozen = {}
    for rel in (0, 14, 15, 1000):
        frozen[rel] = {source: source_endpoint(world, rel, source) for source in SOURCES}
    registry_edges = [
        (edge.rel_id, edge.src, edge.dst, edge.source)
        for edge in world.edges
        if edge.source == "registry"
    ]
    counts = apply_drift(world)
    assert counts["wikidata_to_scraper"] == counts["scraper_to_wikidata"]
    assert counts["wikidata_to_scraper"] > 0
    assert apply_drift(world)["already"] == 1

    for rel in (0, 14):
        assert {source: source_endpoint(world, rel, source) for source in SOURCES} == frozen[rel]
    for rel in (15, 1000):
        after = {source: source_endpoint(world, rel, source) for source in SOURCES}
        assert after["registry"] == frozen[rel]["registry"]
        assert after["wikidata"] == frozen[rel]["scraper"]
        assert after["scraper"] == frozen[rel]["wikidata"]
    still_registry = [
        (edge.rel_id, edge.src, edge.dst, edge.source)
        for edge in world.edges
        if edge.source == "registry"
    ]
    assert still_registry == registry_edges


def test_weighted_search_follows_the_cheap_source_and_the_swap():
    world = generate_world(1)
    rel = 1000
    cheap = {"wikidata": 1.0, "registry": 4.0, "scraper": 9.0}
    before = predict_relation(world, rel, cheap)
    assert before.sources[0] == "wikidata"
    assert before.person == source_endpoint(world, rel, "wikidata")
    wiki_person = before.person
    apply_drift(world)
    after = predict_relation(world, rel, cheap)
    assert after.sources[0] == "wikidata"
    assert after.person == source_endpoint(world, rel, "wikidata")
    assert after.person != wiki_person or source_endpoint(world, rel, "scraper") == wiki_person


def test_no_edge_is_pinned_to_zero_and_generator_matches_the_noise_table():
    world = generate_world(2)
    hits = {source: 0 for source in SOURCES}
    total = 0
    for rel in world.heldout_rels:
        total += 1
        for source in SOURCES:
            if source_endpoint(world, rel, source) == world.gold[rel]:
                hits[source] += 1
        prediction = predict_relation(world, rel, {"wikidata": 1.0, "registry": 2.0, "scraper": 6.0})
        assert prediction.weight > 0
        assert is_correct(world, rel, prediction) in (True, False)
    for source, rate in P_CORRECT.items():
        observed = hits[source] / total
        assert abs(observed - rate) < 0.08, (source, observed, rate)


def test_unweighted_tie_break_is_stable_and_not_a_single_source():
    world = generate_world(3)
    winners = []
    for rel in world.heldout_rels[:80]:
        prediction = predict_relation(world, rel, None)
        assert prediction.weight == 2.0
        winners.append(prediction.sources[0])
    assert len(set(winners)) == 3
    again = [predict_relation(world, rel, None).person for rel in world.heldout_rels[:80]]
    assert again == [predict_relation(world, rel, None).person for rel in world.heldout_rels[:80]]
