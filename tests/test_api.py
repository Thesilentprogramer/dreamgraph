from fastapi.testclient import TestClient
import pytest

from dreamgraph.api import _hydra_up, _writer_not_ready, app

client = TestClient(app)


@pytest.fixture
def live_engine():
    if not _hydra_up():
        pytest.skip("HydraDB is not running on :8443; API integration needs the live engine")


def test_seed_retries_until_the_node_owns_the_cell():
    assert _writer_not_ready(RuntimeError("cell cell-0 is not owned by this node; owner: unknown"))
    assert not _writer_not_ready(RuntimeError("parse error"))


def test_healthz_reports_the_engine():
    response = client.get("/healthz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "hydradb" in body
    assert "live_engine" in body


def test_results_export_is_available_without_the_engine():
    results = client.get("/api/results")
    assert results.status_code == 200
    assert results.json()["vuln"]["config"]["held_out"] == 1317


def test_unknown_page_has_real_404_status(monkeypatch, tmp_path):
    from dreamgraph import api

    (tmp_path / "index.html").write_text("<html>DreamGraph app</html>")
    monkeypatch.setattr(api, "DIST", tmp_path)
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "DreamGraph app" in response.text
    assert client.get("/dashboard").status_code == 200


def test_health_and_results_come_from_the_export(live_engine):
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


def test_query_toggle_changes_the_path_on_a_disagreement(live_engine):
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


def test_vuln_query_matches_the_in_process_sum(live_engine):
    document = client.get("/api/results").json()
    rel = document["vuln"]["demo"]["questions"][0]
    learned = client.get("/api/query", params={"rel": rel, "mode": "dreamgraph", "dataset": "vuln"})
    assert learned.status_code == 200
    body = learned.json()
    assert body["computed"] == "hydradb"
    assert body["procedure"] == ("algo.SPpaths" if document["vuln"]["demo"].get("vote") else "algo.SSpaths")
    assert body["dataset"] == "vuln"
    assert body["path"][0]["kind"] == "question"
    assert body["path"][-1]["kind"] == "verdict"
    from dreamgraph.learner import CostBook
    from dreamgraph.search import predict_relation, vote_world
    from dreamgraph.vuln_world import generate_vuln_world

    demo = document["vuln"]["demo"]
    world = generate_vuln_world(demo["seed"])
    if demo.get("vote"):
        pair = {}
        for key, value in (demo.get("conditional") or {}).items():
            source, _, name = key.partition("|")
            pair[(source, name)] = float(value)
        book = CostBook({key: float(value) for key, value in demo["costs"].items()}, pair)
        prediction = vote_world(
            world, rel, book, k=int(demo["vote"]["k"]), margin=demo["vote"].get("margin"), conditional=True
        )
    else:
        prediction = predict_relation(world, rel, demo["costs"])
    assert body["person"] == prediction.person
    assert len(body["path"]) == len(prediction.path)


def test_live_load_returns_percentiles(live_engine):
    payload = client.get("/api/load", params={"live": 1}).json()
    live = payload["live"]
    assert live["n"] == 300
    assert live["backend"] == "hydradb"
    assert live["p50_ms"] <= live["p95_ms"] <= live["p99_ms"]
    assert payload["recorded"]["n"] > 0


def test_verdict_known_tag_uses_weighted_vote(monkeypatch):
    from dreamgraph import api
    from dreamgraph.search import Prediction

    class FakeGraph:
        def stamp_source_costs(self, costs, rel):
            assert costs and all(cost > 0 for cost in costs.values())

        def voted_paths(self, world, rel, *, k, margin):
            assert (k, margin) == (5, 0.15)
            chain = world.chains[rel][0]
            source = world.edges[chain.edge_indexes[0]].source
            end = chain.person
            return Prediction(end, (world.leaf[rel], end), (source,), 1.0), [(1.0, end, (world.leaf[rel], end), (source,))]

    monkeypatch.setattr(api, "_hydra_up", lambda: True)
    monkeypatch.setattr(api, "_ensure_vuln_edge", lambda world, rel: FakeGraph())
    response = client.get("/api/verdict", params={"cve": "CVE-2023-3745", "package": "ImageMagick", "version": "7.0.11-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] in {"affected", "not_affected"}
    assert body["gold_label"] == "not_affected"
    assert body["policy_version"] == 7
    assert body["procedure"] == "algo.SPpaths"
    assert body["trust_paths"][0]["trust_cost"] > 0
    assert body["trust_paths"][0]["claim"] in {"affected", "not_affected"}
    assert 0 <= body["confidence"] <= 1
    assert client.post("/api/verdict", json=[{"cve": "CVE-2023-3745", "package": "ImageMagick", "version": "7.0.11-1"}]).status_code == 200


def test_verdict_unknown_tag_and_invalid_input():
    response = client.get("/api/verdict", params={"cve": "CVE-2099-99999", "package": "Imaginary", "version": "1.0"})
    assert response.status_code == 404
    assert "not in the Zenodo graph" in response.json()["detail"]
    assert client.get("/api/verdict", params={"cve": "bad", "package": "Imaginary", "version": "1.0"}).status_code == 422


def test_mcp_http_endpoint_initializes_at_exact_url():
    with TestClient(app, base_url="https://dreamgraph.onrender.com") as mounted:
        response = mounted.post(
            "/mcp",
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
            },
            headers={"accept": "application/json, text/event-stream", "content-type": "application/json"},
        )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "DreamGraph"
