"""Runtime knobs. Defaults match the stress-test revisions in AGENTS.md."""

from __future__ import annotations

import os

SOURCES: tuple[str, ...] = ("wikidata", "registry", "scraper")

# Synthetic observation noise. These are generator parameters, not measured rates.
P_CORRECT: dict[str, float] = {
    "wikidata": 0.88,
    "registry": 0.72,
    "scraper": 0.30,
}

HAND_SET_COSTS: dict[str, float] = {
    "wikidata": 1.0,
    "registry": 2.0,
    "scraper": 6.0,
}

REL_TYPE: dict[str, str] = {
    "wikidata": "OWNS_WIKIDATA",
    "registry": "OWNS_REGISTRY",
    "scraper": "OWNS_SCRAPER",
}

BM25_QUERY: tuple[str, ...] = ("wikidata", "authoritative", "ownership")

DRIFT_ITER = int(os.environ.get("DG_DRIFT_ITER", "4"))
WINDOW = int(os.environ.get("DG_WINDOW", "100"))
HELD_OUT = int(os.environ.get("DG_HELD_OUT", "300"))
SEEDS = tuple(
    int(part) for part in os.environ.get("DG_SEEDS", "0,1,2").split(",") if part.strip()
)
ITERS = int(os.environ.get("DG_ITERS", "8"))
BATCH = int(os.environ.get("DG_BATCH", "40"))
GUARD = int(os.environ.get("DG_GUARD", "20"))
DRIFT_MIN_REL = int(os.environ.get("DG_DRIFT_MIN_REL", "15"))
TRAIN_REL_COUNT = int(os.environ.get("DG_TRAIN_RELS", "120"))
BOOTSTRAP = int(os.environ.get("DG_BOOTSTRAP", "1000"))
GREEDY_DECAY = float(os.environ.get("DG_GREEDY_DECAY", "0.85"))

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0")

HYDRA_URL = os.environ.get("DG_HYDRA_URL", "http://127.0.0.1:8443")
HYDRA_TOKEN = os.environ.get("DG_HYDRA_TOKEN", "local-development-token-32-bytes")
HYDRA_CELL = os.environ.get("DG_HYDRA_CELL", "cell-0")
HYDRA_GRAPH = os.environ.get("DG_HYDRA_GRAPH", "default")
BACKEND = os.environ.get("DG_BACKEND", "memory")

S3_BUCKET = os.environ.get("DG_S3_BUCKET", os.environ.get("AWS_S3_BUCKET", "dreamgraph"))
S3_ENDPOINT = os.environ.get("DG_S3_ENDPOINT") or os.environ.get("AWS_ENDPOINT_URL")
S3_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
S3_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "testing")
S3_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "testing")

IMAGE = "ghcr.io/hydra-db/hydradb:0.4.0"


def uniform_costs() -> dict[str, float]:
    return {source: 1.0 for source in SOURCES}
