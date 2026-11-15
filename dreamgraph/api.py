"""Dashboard API. Chart numbers are read from the benchmark export, never typed in."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from dreamgraph.bench import EXPORT, percentile
from dreamgraph.config import SOURCES
from dreamgraph.search import predict_relation
from dreamgraph.world import apply_drift, generate_world, source_endpoint

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


def _path_payload(world, rel_id: int, mode: str, costs: dict | None) -> dict:
    prediction = predict_relation(world, rel_id, costs)
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
    for source in SOURCES:
        person = source_endpoint(world, rel_id, source)
        alternatives.append(
            {
                "source": source,
                "person": person,
                "person_name": None if person is None else world.names.get(person),
                "correct": person == gold,
                "chosen": bool(prediction.sources) and prediction.sources[0] == source,
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
        "computed": "live",
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "dreamgraph", "results": EXPORT.exists()}


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
    document = load_results()
    world = demo_world(document)
    if rel not in world.leaf:
        raise HTTPException(status_code=404, detail=f"unknown relation {rel}")
    costs = None if mode == "unweighted" else document["demo"]["costs"]
    return _path_payload(world, rel, mode, costs)


@app.get("/api/load")
def load(live: int = 0) -> dict:
    document = load_results()
    recorded = document["load"]
    if not live:
        return {"recorded": recorded, "live": None}
    world = demo_world(document)
    costs = document["demo"]["costs"]
    samples = world.heldout_rels[:300]
    timings = []
    for rel_id in samples:
        started = time.perf_counter()
        predict_relation(world, rel_id, costs)
        timings.append((time.perf_counter() - started) * 1000.0)
    return {
        "recorded": recorded,
        "live": {
            "backend": "memory",
            "what": "Live remeasure of DreamGraph searches on the drifted demo world.",
            "n": len(timings),
            "p50_ms": round(percentile(timings, 0.50), 6),
            "p95_ms": round(percentile(timings, 0.95), 6),
            "p99_ms": round(percentile(timings, 0.99), 6),
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
