import uuid

import pytest

from dreamgraph.hydra_client import (
    HydraClient,
    HydraError,
    build_sp_paths,
    build_ss_paths,
    parse_path_cell,
    path_budget,
)


class Capture:
    def __init__(self, payload=None):
        self.bodies = []
        self.payload = payload or {"columns": [], "rows": [], "query_id": "server-side"}

    def __call__(self, body):
        self.bodies.append(body)
        return self.payload


def test_path_budget_is_a_total_cap():
    budget = path_budget(4)
    assert budget == {"pathCount": 4, "resultLimit": 4}
    with pytest.raises(ValueError):
        path_budget(0)


def test_each_request_has_a_fresh_query_id_and_cell():
    capture = Capture()
    client = HydraClient(capture, cell_id="cell-0")
    cypher, params = build_ss_paths(src=7, weighted=True, total=4)
    client.query(cypher, params)
    client.query("MATCH (n:Entity {id: $id}) RETURN n.id AS id", {"id": 7})
    assert len(capture.bodies) == 2
    ids = [body["query_id"] for body in capture.bodies]
    assert ids[0] != ids[1]
    for body in capture.bodies:
        uuid.UUID(body["query_id"])
        assert body["cell_id"] == "cell-0"
        assert "query" in body
    assert "resultLimit: $resultLimit" in capture.bodies[0]["query"]
    assert capture.bodies[0]["parameters"]["pathCount"] == 4
    assert capture.bodies[0]["parameters"]["resultLimit"] == 4
    assert "weightProp: 'cost'" in capture.bodies[0]["query"]
    assert "relTypes: ['OWNS_WIKIDATA', 'OWNS_REGISTRY', 'OWNS_SCRAPER']" in capture.bodies[0]["query"]


def test_unweighted_call_omits_weight_and_sp_paths_has_a_target():
    cypher, params = build_ss_paths(src=3, weighted=False, total=2)
    assert "weightProp" not in cypher
    assert params["resultLimit"] == 2
    sp, sp_params = build_sp_paths(src=3, dst=9, weighted=True, total=2)
    assert "algo.SPpaths" in sp
    assert sp_params["dst"] == 9
    assert "targetNode: $dst" in sp


def test_path_count_is_not_scaled_by_pairs():
    _, params = build_ss_paths(src=1, weighted=True, total=4)
    assert params["pathCount"] == 4
    assert params["resultLimit"] == 4


def test_error_and_422_are_raised():
    client = HydraClient(lambda body: {"error": {"code": "invalid_request", "message": "nope"}})
    with pytest.raises(HydraError, match="nope"):
        client.query("RETURN 1")
    bare = HydraClient(lambda body: {})
    with pytest.raises(HydraError, match="422"):
        bare.query("RETURN 1")


def test_path_cell_decoder_unwraps_capitalised_tags():
    cell = {
        "type": "path",
        "value": {
            "nodes": [
                {"id": 1, "labels": ["Entity"], "properties": {"name": {"String": "Northwind"}}},
                {"id": 2, "labels": ["Entity"], "properties": {"name": {"String": "Avery"}}},
            ],
            "relationships": [
                {
                    "id": None,
                    "edge_type": "OWNS_WIKIDATA",
                    "src": 1,
                    "dst": 2,
                    "properties": {"cost": {"Float": 1.0}, "source": {"String": "wikidata"}},
                }
            ],
        },
    }
    parsed = parse_path_cell(cell)
    assert parsed["nodes"][0]["properties"]["name"] == "Northwind"
    assert parsed["relationships"][0]["properties"]["cost"] == 1.0
    assert parsed["relationships"][0]["type"] == "OWNS_WIKIDATA"
    assert parsed["relationships"][0]["src"] == 1


def test_null_cell_has_no_value_key():
    capture = Capture(
        {
            "columns": ["name"],
            "rows": [[{"type": "null"}]],
        }
    )
    client = HydraClient(capture)
    assert client.rows("MATCH (n {id: 1}) RETURN n.name AS name") == [[None]]
