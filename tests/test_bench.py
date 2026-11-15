import json

from dreamgraph.bench import EXPORT


def test_export_is_a_live_hydradb_run():
    document = json.loads(EXPORT.read_text())
    assert document["backend"] == "hydradb"
    assert document["hydra_verified"] is True
    assert document["synthetic_noise"] is True
    assert document["config"]["held_out"] == 300
    assert document["config"]["seeds"] == [0, 1, 2]
    assert document["drift_iter"] == 4
    dream = document["series"]["dreamgraph"]
    frozen = document["series"]["frozen_at_3"]["accuracy"]
    plain = document["series"]["unweighted"]
    assert dream["accuracy"][3] < dream["accuracy"][1] - 0.15
    assert dream["accuracy"][-1] > dream["accuracy"][3] + 0.15
    assert frozen[-1] < dream["accuracy"][-1] - 0.1
    assert plain["hop3_rate"][0] == 0.0
    assert dream["hop3_rate"][1] > 0.5
    assert document["load"]["clients"] == 20
    assert document["load"]["p50_ms"] <= document["load"]["p95_ms"] <= document["load"]["p99_ms"]
    assert document["load"]["n"] == 600
