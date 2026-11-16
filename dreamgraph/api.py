"""Dashboard API. Chart numbers are read from the benchmark export, never typed in."""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from dreamgraph.bench import EXPORT, percentile
from dreamgraph.config import HYDRA_TOKEN, HYDRA_URL
from dreamgraph.hydra_graph import HydraGraph, concurrent_latencies
from dreamgraph.learner import CostBook
from dreamgraph.mcp import mcp
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
    async with mcp.session_manager.run():
        if os.environ.get("DG_SEED_ON_BOOT") == "1":
            threading.Thread(target=_seed_on_boot, name="dreamgraph-seed", daemon=True).start()
        yield


app = FastAPI(title="DreamGraph", version="0.1.0", lifespan=_lifespan)


class _MCPPrefix:
    """Serve the mounted root route at /mcp without a trailing-slash redirect."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.inner(scope, receive, send)


app.add_middleware(_MCPPrefix)
app.mount("/mcp", mcp.streamable_http_app())


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


class VerdictRequest(BaseModel):
    cve: str = Field(..., pattern=r"^CVE-\d{4}-\d{4,}$", max_length=32, examples=["CVE-2023-3745"])
    package: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+/-]*$", examples=["ImageMagick"])
    version: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+~:-]*$", examples=["7.0.11-1"])


def _verdict(request: VerdictRequest) -> dict:
    document = load_results()
    world = vuln_world(document)
    wanted = f"{request.package} {request.version} · {request.cve}".casefold()
    rel = next((rel for rel, leaf in world.leaf.items() if world.names[leaf].casefold() == wanted), None)
    if rel is None:
        raise HTTPException(status_code=404, detail="Tag is not in the Zenodo graph")
    if not _hydra_up():
        raise HTTPException(status_code=503, detail="HydraDB is not answering on :8443")

    demo = document["vuln"]["demo"]
    policies = [row for row in document["vuln"]["policies"] if row["seed"] == demo["seed"] and row["costs"] == demo["costs"]]
    if not policies:
        raise HTTPException(status_code=503, detail="Published demo costs have no matching PolicyVersion")
    policy = policies[-1]
    pair = {}
    for key, value in demo["conditional"].items():
        feed, _, project = key.partition("|")
        pair[(feed, project)] = float(value)
    book = CostBook({feed: float(cost) for feed, cost in demo["costs"].items()}, pair)
    project = world.projects[rel]
    graph = _ensure_vuln_edge(world, rel)
    feeds = {world.edges[index].source for chain in world.chains[rel] for index in chain.edge_indexes}
    graph.stamp_source_costs({feed: book.weight(feed, project) for feed in feeds}, rel)
    vote = demo["vote"]
    prediction, found = graph.voted_paths(world, rel, k=int(vote["k"]), margin=float(vote["margin"]))
    ranked = sorted(found, key=lambda item: (item[0], item[1]))[:int(vote["k"])]
    eligible = [item for item in ranked if item[0] <= ranked[0][0] + float(vote["margin"]) + 1e-9] if ranked else []
    scores = {}
    for weight, end, *_ in eligible:
        scores[end] = scores.get(end, 0.0) + math.exp(-weight)
    confidence = round(scores.get(prediction.person, 0.0) / sum(scores.values()), 6) if scores else 0.0
    paths = []
    for weight, end, _nodes, sources in ranked:
        feed = sources[0] if sources else "unknown"
        paths.append({
            "feed": feed,
            "trust_cost": round(book.weight(feed, project), 6) if feed != "unknown" else None,
            "path_cost": round(weight, 6),
            "claim": world.names[end].replace(" ", "_"),
            "in_vote": (weight, end, _nodes, sources) in eligible,
        })
    label = world.names.get(prediction.person, "unknown").replace(" ", "_")
    return {
        "cve": request.cve,
        "package": request.package,
        "version": request.version,
        "verdict": label,
        "confidence": confidence,
        "confidence_note": "Share of exp(-path cost) votes within 0.15 of the cheapest top-5 path; not a calibrated probability.",
        "trust_paths": paths,
        "policy_version": policy["version"],
        "gold_label": world.names[world.gold[rel]].replace(" ", "_"),
        "procedure": "algo.SPpaths",
    }


@app.get("/api/verdict", summary="Check a vulnerability tag using live HydraDB weighted paths")
def get_verdict(
    cve: str = Query(..., pattern=r"^CVE-\d{4}-\d{4,}$", max_length=32),
    package: str = Query(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+/-]*$"),
    version: str = Query(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+~:-]*$"),
) -> dict:
    return _verdict(VerdictRequest(cve=cve, package=package, version=version))


@app.post("/api/verdict", summary="Check one tag or a batch of up to 20")
def post_verdict(request: VerdictRequest | list[VerdictRequest]) -> dict | list[dict]:
    if isinstance(request, list):
        if not request or len(request) > 20:
            raise HTTPException(status_code=422, detail="Batch must contain 1–20 tags")
        return [_verdict(item) for item in request]
    return _verdict(request)


@app.post("/api/verdict/batch", summary="Check up to 20 tags")
def batch_verdict(requests: list[VerdictRequest]) -> list[dict]:
    return post_verdict(requests)


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
    if not candidate.is_relative_to(DIST.resolve()):
        raise HTTPException(status_code=404, detail="not found")
    if not candidate.is_file():
        page = DIST / "index.html"
        if page.exists() and (asset_path == "dashboard" or asset_path.startswith("dashboard/") or asset_path == "graph" or asset_path.startswith("graph/")):
            return FileResponse(page)
        if page.exists() and "." not in Path(asset_path).name:
            return FileResponse(page, status_code=404)
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(candidate)
