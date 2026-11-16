import json
from pathlib import Path

from fastapi.testclient import TestClient

from dreamgraph.api import app
from dreamgraph.explorer_graph import NODE_CAP, build_explorer

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_explorer_graph_stays_under_the_cap_and_matches_the_file():
    built = build_explorer()
    assert 100 < built["node_count"] <= NODE_CAP
    assert built["node_count"] == len(built["nodes"])
    assert any(node["type"] == "group" and node["count"] >= 3 for node in built["nodes"])
    assert all(node.get("count", 3) >= 3 for node in built["nodes"] if node["type"] == "group")
    assert any(node["type"] == "feed" for node in built["nodes"])
    assert len(built["iterations"]) == 8
    assert built["iterations"][3]["drift"] is True
    assert built["queries"]
    on_disk = json.loads((ROOT / "results" / "explorer.json").read_text())
    assert on_disk["node_count"] == built["node_count"]
    assert on_disk["iterations"][-1]["costs"]["nvd"] == built["iterations"][-1]["costs"]["nvd"]


def test_explorer_route_serves_the_precomputed_graph():
    response = client.get("/api/explorer")
    assert response.status_code == 200
    body = response.json()
    assert body["node_count"] <= NODE_CAP
    assert body["links"]
    main = (ROOT / "web" / "src" / "main.jsx").read_text()
    assert "react-force-graph" not in (ROOT / "web" / "src" / "App.jsx").read_text()
    assert "react-force-graph" not in main
    assert "import(" in main
