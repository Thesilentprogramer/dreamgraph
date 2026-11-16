"""Dashboard API. Chart numbers are read from the benchmark export, never typed in."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from dreamgraph.bench import EXPORT, percentile
from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL
from dreamgraph.hydra_graph import HydraGraph, concurrent_latencies
from dreamgraph.search import Prediction
from dreamgraph.vuln_world import generate_vuln_world
from dreamgraph.world import World, apply_drift, generate_world

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"

_world_cache: dict = {}
_load_lock = threading.Lock()
_boot = {"seeding": False, "seeded": False, "error": None}


def _writer_not_ready(exc: BaseException) -> bool:
    return "not owned by this node" in str(exc)


def _seed_on_boot() -> None:
    """Load the demo world once this node owns cell-0.

    /healthz answers before the writer lease is claimed. On a slow CPU that
    gap is long enough for the first MERGE to fail with owner: unknown.
    """

    _boot["seeding"] = True
    _boot["error"] = None
    deadline = time.monotonic() + 300
    delay = 2.0
    try:
        while True:
            if not _hydra_up():
                if time.monotonic() >= deadline:
                    _boot["error"] = "HydraDB did not open /healthz"
                    return
            else:
                try:
                    document = load_results()
                    world = demo_world(document)
                    graph = _ensure_loaded(world)
                    graph.stamp_source_costs(document["demo"]["costs"])
                    _boot["seeded"] = True
                    _boot["error"] = None
                    return
                except Exception as exc:  # noqa: BLE001 — surfaced on /api/health
                    _boot["error"] = str(exc)
                    if not _writer_not_ready(exc) or time.monotonic() >= deadline:
                        return
            threading.Event().wait(delay)
            delay = min(delay * 1.5, 15.0)
    finally:
        _boot["seeding"] = False


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.environ.get("DG_SEED_ON_BOOT") == "1":
        threading.Thread(target=_seed_on_boot, name="dreamgraph-seed", daemon=True).start()
    yield


app = FastAPI(title="DreamGraph", version="0.1.0", lifespan=_lifespan)


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


def vuln_world(document: dict) -> World:
    vuln = document.get("vuln") or {}
    demo = vuln.get("demo") or {}
    if "seed" not in demo:
        raise HTTPException(status_code=404, detail="Vulnerability slice is not in this export.")
    key = ("vuln", demo["seed"])
    if _world_cache.get("vuln_key") != key:
        _world_cache["vuln_key"] = key
        _world_cache["vuln_world"] = generate_vuln_world(demo["seed"])
    return _world_cache["vuln_world"]


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
    with _load_lock:
        if _world_cache.get("loaded") != key:
            graph.load(world)
            _world_cache["loaded"] = key
            _boot["seeded"] = True
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
        label = sources[0] if len(set(sources)) == 1 else " ".join(sources)
        alternatives.append(
            {
                "name": chain.name,
                "source": " ".join(sources),
                "label": label,
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
        "dataset": "vuln" if world.kinds.get(world.leaf[rel_id]) == "question" else "synthetic",
    }


@app.get("/healthz")
def healthz():
    """Render health check. 200 only after HydraDB itself answers."""

    up = _hydra_up()
    body = {
        "status": "ok" if up else "starting",
        "hydradb": up,
        "live_engine": up,
        "seeded": _boot["seeded"],
        "seeding": _boot["seeding"],
    }
    if not up:
        return JSONResponse(body, status_code=503)
    return body


@app.get("/api/health")
def health() -> dict:
    up = _hydra_up()
    return {
        "status": "ok" if up else "starting",
        "service": "dreamgraph",
        "results": EXPORT.exists(),
        "hydradb": up,
        "live_engine": up,
        "seeded": _boot["seeded"],
        "seeding": _boot["seeding"],
        "seed_error": _boot["error"],
    }


@app.get("/api/results")
def results() -> dict:
    return load_results()


@app.get("/api/explorer")
def explorer() -> dict:
    """Precomputed 3D graph. It does not refit costs or call the learner."""

    path = ROOT / "results" / "explorer.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="results/explorer.json is missing.")
    return json.loads(path.read_text())


def _ensure_vuln_edge(world: World, rel: int) -> HydraGraph:
    graph = _graph()
    loaded = _world_cache.setdefault("vuln_rels", set())
    with _load_lock:
        if rel not in loaded:
            graph.load(world, rel_ids={rel})
            loaded.add(rel)
    return graph


@app.get("/api/query")
def query(
    rel: int = Query(..., description="Relation id from the benchmark demo list"),
    mode: str = Query("dreamgraph"),
    dataset: str = Query("synthetic"),
) -> dict:
    if mode not in {"dreamgraph", "unweighted"}:
        raise HTTPException(status_code=400, detail="mode must be dreamgraph or unweighted")
    if dataset not in {"synthetic", "vuln"}:
        raise HTTPException(status_code=400, detail="dataset must be synthetic or vuln")
    if not _hydra_up():
        raise HTTPException(status_code=503, detail="HydraDB is not answering on :8443")
    document = load_results()
    if dataset == "vuln":
        world = vuln_world(document)
        if rel not in world.leaf:
            raise HTTPException(status_code=404, detail=f"unknown vulnerability question {rel}")
        demo = document["vuln"]["demo"]
        costs = None if mode == "unweighted" else demo["costs"]
        vote = demo.get("vote")
        graph = _ensure_vuln_edge(world, rel)
        if costs is not None:
            if vote:
                project = world.projects.get(rel)
                pair = {}
                for key, value in (demo.get("conditional") or {}).items():
                    source, _, name = key.partition("|")
                    pair[(source, name)] = float(value)
                from dreamgraph.learner import CostBook

                book = CostBook({key: float(value) for key, value in costs.items()}, pair)
                present = {edge.source for edge in world.edges if edge.rel_id == rel}
                graph.stamp_source_costs({source: book.weight(source, project) for source in present}, rel)
            else:
                graph.stamp_source_costs(costs, rel)
    else:
        world = demo_world(document)
        if rel not in world.leaf:
            raise HTTPException(status_code=404, detail=f"unknown relation {rel}")
        costs = None if mode == "unweighted" else document["demo"]["costs"]
        graph = _ensure_loaded(world)
        if costs is not None:
            graph.stamp_source_costs(costs)
    vote_spec = document["vuln"]["demo"].get("vote") if dataset == "vuln" else None
    if vote_spec and costs is not None:
        prediction = graph.voted_owner(world, rel, k=int(vote_spec["k"]), margin=vote_spec.get("margin"))
    else:
        prediction = graph.owner(world, rel, costs)
    payload = _path_payload(world, rel, mode, costs, prediction)
    if vote_spec and costs is not None:
        payload["procedure"] = "algo.SPpaths"
    return payload


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
