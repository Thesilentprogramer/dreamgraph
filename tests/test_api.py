from fastapi.testclient import TestClient

from dreamgraph.api import app

client = TestClient(app)


def test_health_and_results_come_from_the_export():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    results = client.get("/api/results")
    assert results.status_code == 200
    body = results.json()
    assert body["series"]["dreamgraph"]["accuracy"]
    assert body["backend"] == "memory"
    assert body["synthetic_noise"] is True


def test_query_toggle_changes_the_path_on_a_disagreement():
    document = client.get("/api/results").json()
    rel = document["demo"]["disagree"][0]
    learned = client.get("/api/query", params={"rel": rel, "mode": "dreamgraph"})
    plain = client.get("/api/query", params={"rel": rel, "mode": "unweighted"})
    assert learned.status_code == plain.status_code == 200
    assert learned.json()["person"] != plain.json()["person"]
    assert learned.json()["computed"] == "live"
    assert learned.json()["path"][0]["kind"] == "company"
    assert learned.json()["path"][-1]["kind"] == "person"
    assert learned.json()["drift_applied"] is True
    bad = client.get("/api/query", params={"rel": rel, "mode": "shortcut"})
    assert bad.status_code == 400


def test_live_load_returns_percentiles():
    payload = client.get("/api/load", params={"live": 1}).json()
    live = payload["live"]
    assert live["n"] == 300
    assert live["p50_ms"] <= live["p95_ms"] <= live["p99_ms"]
    assert payload["recorded"]["n"] > 0
