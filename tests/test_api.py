from fastapi.testclient import TestClient

from dreamgraph.api import _writer_not_ready, app

client = TestClient(app)


def test_seed_retries_until_the_node_owns_the_cell():
    assert _writer_not_ready(RuntimeError("cell cell-0 is not owned by this node; owner: unknown"))
    assert not _writer_not_ready(RuntimeError("parse error"))


def test_healthz_reports_the_engine():
    response = client.get("/healthz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "hydradb" in body
    assert "live_engine" in body


def test_health_and_results_come_from_the_export():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    results = client.get("/api/results")
    assert results.status_code == 200
    body = results.json()
    assert body["series"]["dreamgraph"]["accuracy"]
    assert body["backend"] == "hydradb"
    assert body["hydra_verified"] is True
    assert body["synthetic_noise"] is True


def test_query_toggle_changes_the_path_on_a_disagreement():
    document = client.get("/api/results").json()
    rel = document["demo"]["disagree"][0]
    learned = client.get("/api/query", params={"rel": rel, "mode": "dreamgraph"})
    plain = client.get("/api/query", params={"rel": rel, "mode": "unweighted"})
    assert learned.status_code == plain.status_code == 200
    assert learned.json()["computed"] == "hydradb"
    assert learned.json()["procedure"] == "algo.SSpaths"
    assert len(learned.json()["path"]) != len(plain.json()["path"]) or learned.json()["person"] != plain.json()["person"]
    assert learned.json()["path"][0]["kind"] == "company"
    assert learned.json()["path"][-1]["kind"] == "person"
    assert learned.json()["drift_applied"] is True
    bad = client.get("/api/query", params={"rel": rel, "mode": "shortcut"})
    assert bad.status_code == 400


def test_vuln_query_matches_the_in_process_sum():
    document = client.get("/api/results").json()
    rel = document["vuln"]["demo"]["questions"][0]
    learned = client.get("/api/query", params={"rel": rel, "mode": "dreamgraph", "dataset": "vuln"})
    assert learned.status_code == 200
    body = learned.json()
    assert body["computed"] == "hydradb"
    assert body["procedure"] == "algo.SSpaths"
    assert body["dataset"] == "vuln"
    assert body["path"][0]["kind"] == "question"
    assert body["path"][-1]["kind"] == "verdict"
    from dreamgraph.search import predict_relation
    from dreamgraph.vuln_world import generate_vuln_world

    world = generate_vuln_world(document["vuln"]["demo"]["seed"])
    prediction = predict_relation(world, rel, document["vuln"]["demo"]["costs"])
    assert body["person"] == prediction.person
    assert len(body["path"]) == len(prediction.path)


def test_live_load_returns_percentiles():
    payload = client.get("/api/load", params={"live": 1}).json()
    live = payload["live"]
    assert live["n"] == 300
    assert live["backend"] == "hydradb"
    assert live["p50_ms"] <= live["p95_ms"] <= live["p99_ms"]
    assert payload["recorded"]["n"] > 0
