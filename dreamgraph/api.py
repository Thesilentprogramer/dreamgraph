"""Dashboard API. Chart numbers are read from the benchmark export, never typed in."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from dreamgraph.bench import EXPORT, percentile
from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL
from dreamgraph.hydra_graph import HydraGraph, concurrent_latencies
from dreamgraph.search import Prediction
from dreamgraph.world import World, apply_drift, generate_world

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"

app = FastAPI(title="DreamGraph", version="0.1.0")

_world_cache: dict = {}


def load_results() -> dict:
    if not EXPORT.exists():
        raise HTTPException(
            status_code=404,
            detail="results/summary.json is missing. Run make bench.",
        )
    return json.loads(EXPORT.read_text())


def demo_world(document: dict):
    demo = document["demo"]
    key = (demo["seed"], bool(demo["drift_applied"]))
    cached = _world_cache.get("key")
    if cached != key:
        world = generate_world(demo["seed"])
        if demo["drift_applied"]:
            apply_drift(world)
        _world_cache["key"] = key
        _world_cache["world"] = world
    return _world_cache["world"]


def _hydra_up() -> bool:
    try:
        with urllib.request.urlopen(f"{HYDRA_URL}/healthz", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _graph() -> HydraGraph:
    graph = _world_cache.get("graph")
    if graph is None:
        graph = HydraGraph(HYDRA_URL, HYDRA_TOKEN)
        _world_cache["graph"] = graph
    return graph


def _ensure_loaded(world: World) -> HydraGraph:
    graph = _graph()
    key = (world.seed, world.drifted, len(world.edges))
    if _world_cache.get("loaded") != key:
        graph.load(world)
        _world_cache["loaded"] = key
    return graph


def _path_payload(world, rel_id: int, mode: str, costs: dict | None, prediction: Prediction) -> dict:
    nodes = [
        {
            "id": node_id,
            "name": world.names.get(node_id, str(node_id)),
            "kind": world.kinds.get(node_id, "node"),
        }
        for node_id in prediction.path
    ]
    edges = [
        {"source": source, "from": prediction.path[index], "to": prediction.path[index + 1]}
        for index, source in enumerate(prediction.sources)
    ]
    gold = world.gold[rel_id]
    alternatives = []
    for chain in world.chains[rel_id]:
        sources = tuple(world.edges[index].source for index in chain.edge_indexes)
        alternatives.append(
            {
                "source": " ".join(sources),
                "hops": len(sources),
                "person": chain.person,
                "person_name": world.names.get(chain.person),
                "correct": chain.person == gold,
                "chosen": sources == prediction.sources,
            }
        )
    return {
        "rel_id": rel_id,
        "mode": mode,
        "company": world.names[world.leaf[rel_id]],
        "gold_person": gold,
        "gold_name": world.names.get(gold),
        "person": prediction.person,
        "person_name": None if prediction.person is None else world.names.get(prediction.person),
        "correct": prediction.person == gold,
        "weight": None if prediction.weight == float("inf") else round(prediction.weight, 6),
        "path": nodes,
        "edges": edges,
        "alternatives": alternatives,
        "drift_applied": world.drifted,
        "computed": "hydradb",
        "procedure": "algo.SSpaths",
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "dreamgraph",
        "results": EXPORT.exists(),
        "hydradb": _hydra_up(),
    }


@app.get("/api/results")
def results() -> dict:
    return load_results()


@app.get("/api/query")
def query(
    rel: int = Query(..., description="Relation id from the benchmark demo list"),
    mode: str = Query("dreamgraph"),
) -> dict:
    if mode not in {"dreamgraph", "unweighted"}:
        raise HTTPException(status_code=400, detail="mode must be dreamgraph or unweighted")
    if not _hydra_up():
        raise HTTPException(status_code=503, detail="HydraDB is not answering on :8443")
    document = load_results()
    world = demo_world(document)
    if rel not in world.leaf:
        raise HTTPException(status_code=404, detail=f"unknown relation {rel}")
    costs = None if mode == "unweighted" else document["demo"]["costs"]
    graph = _ensure_loaded(world)
    if costs is not None:
        graph.stamp_source_costs(costs)
    prediction = graph.owner(world, rel, costs)
    return _path_payload(world, rel, mode, costs, prediction)


@app.get("/api/load")
def load(live: int = 0) -> dict:
    document = load_results()
    recorded = document["load"]
    if not live:
        return {"recorded": recorded, "live": None}
    if not _hydra_up():
        raise HTTPException(status_code=503, detail="HydraDB is not answering on :8443")
    world = demo_world(document)
    graph = _ensure_loaded(world)
    graph.stamp_source_costs(document["demo"]["costs"])
    timings = concurrent_latencies(
        HYDRA_URL,
        HYDRA_TOKEN,
        world.leaf[world.heldout_rels[0]],
        rounds=15,
        clients=20,
    )
    return {
        "recorded": recorded,
        "live": {
            "backend": "hydradb",
            "clients": 20,
            "what": "Live remeasure: 20 concurrent clients calling weighted algo.SSpaths.",
            "n": len(timings),
            "p50_ms": round(percentile(timings, 0.50), 4),
            "p95_ms": round(percentile(timings, 0.95), 4),
            "p99_ms": round(percentile(timings, 0.99), 4),
        },
    }


@app.get("/")
def index():
    page = DIST / "index.html"
    if not page.exists():
        raise HTTPException(status_code=503, detail="Dashboard bundle missing. Run make web.")
    return FileResponse(page)


@app.get("/{asset_path:path}")
def assets(asset_path: str):
    if asset_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    candidate = (DIST / asset_path).resolve()
    if not str(candidate).startswith(str(DIST.resolve())) or not candidate.is_file():
        page = DIST / "index.html"
        if page.exists():
            return FileResponse(page)
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(candidate)
