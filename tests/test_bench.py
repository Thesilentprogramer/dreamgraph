import json

from dreamgraph.bench import EXPORT, METHODS, run_benchmark


def test_fresh_run_matches_the_exported_series_and_recovers():
    fresh = run_benchmark()
    committed = json.loads(EXPORT.read_text())
    assert fresh["series"] == committed["series"]
    assert committed["backend"] == "memory"
    assert committed["hydra_verified"] is False
    assert committed["synthetic_noise"] is True
    assert committed["config"]["held_out"] == 300
    assert committed["config"]["seeds"] == [0, 1, 2]
    assert committed["drift_iter"] == 4
    assert committed["config"]["no_gold_pinning"] is True
    for method in METHODS:
        series = committed["series"][method]
        assert len(series["accuracy"]) == 8
        assert len(series["ci_low"]) == len(series["ci_high"]) == 8
        for point, low, high in zip(series["accuracy"], series["ci_low"], series["ci_high"]):
            assert low <= point <= high

    dream = committed["series"]["dreamgraph"]["accuracy"]
    frozen = committed["series"]["frozen_at_3"]["accuracy"]
    hand = committed["series"]["hand_set"]["accuracy"]
    plain = committed["series"]["unweighted"]["accuracy"]
    # Iteration 4 is index 3: the drifted score. Later iterations refit on the window.
    assert dream[3] < dream[1] - 0.2
    assert dream[-1] > dream[3] + 0.2
    assert frozen[-1] < dream[-1] - 0.2
    assert hand[-1] < hand[0] - 0.3
    assert plain[0] == plain[-1]
    # Same learner, dict edges. Equality is the honest result.
    assert committed["series"]["dict_learner"]["accuracy"] == dream
    assert any(version["rolled_back"] for version in committed["policies"])
    assert committed["demo"]["disagree"]
    assert committed["load"]["n"] > 0
    assert committed["load"]["p50_ms"] <= committed["load"]["p95_ms"] <= committed["load"]["p99_ms"]
