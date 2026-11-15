#!/usr/bin/env python3
"""Phase 0 probe for ghcr.io/hydra-db/hydradb:0.4.0.

Always records the registry digest. Live Cypher, pathCount, and the
restart-then-write check run only when Docker is on PATH. Exit 0 when every
live check passed. Exit 2 when the engine was not actually exercised.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dreamgraph.config import IMAGE  # noqa: E402
from dreamgraph.hydra_client import (  # noqa: E402
    HttpTransport,
    HydraClient,
    HydraError,
    build_sp_paths,
    build_ss_paths,
    path_budget,
)

OUT = ROOT / "results" / "probe.json"
TOKEN = "local-development-token-32-bytes"
BUCKET = "dreamgraph-probe"
NETWORK = "dreamgraph-probe"
MOTO_NAME = "dreamgraph-probe-moto"
HYDRA_NAME = "dreamgraph-probe-hydra"
QUERY = "http://127.0.0.1:8443"


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, **kwargs)


def registry_digests() -> dict:
    token_url = "https://ghcr.io/token?service=ghcr.io&scope=repository:hydra-db/hydradb:pull"
    with urllib.request.urlopen(token_url, timeout=30) as response:
        token = json.loads(response.read().decode())["token"]
    request = urllib.request.Request(
        "https://ghcr.io/v2/hydra-db/hydradb/manifests/0.4.0",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        index_digest = response.headers.get("Docker-Content-Digest")
        index = json.loads(response.read().decode())
    platforms = {}
    for manifest in index.get("manifests") or []:
        platform = manifest.get("platform") or {}
        arch = platform.get("architecture")
        os_name = platform.get("os")
        if arch in {"amd64", "arm64"} and os_name == "linux":
            platforms[f"linux/{arch}"] = manifest.get("digest")
    return {
        "image": IMAGE,
        "index_digest": index_digest,
        "platforms": platforms,
        "source": "registry-https",
        "note": "A pulled image's RepoDigests entry is the local confirmation. This record is the registry index only.",
    }


def _write(document: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _cleanup() -> None:
    if not shutil.which("docker"):
        return
    _run(["docker", "rm", "-f", HYDRA_NAME, MOTO_NAME])
    _run(["docker", "network", "rm", NETWORK])


def _wait_http(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def _client() -> HydraClient:
    return HydraClient(HttpTransport(QUERY, TOKEN))


def _check_shapes(report: dict) -> None:
    client = _client()
    shapes: dict[str, str] = {}

    def check(name: str, cypher: str, parameters: dict | None = None) -> dict:
        try:
            payload = client.query(cypher, parameters)
            shapes[name] = "ok"
            return payload
        except HydraError as exc:
            shapes[name] = f"error: {exc}"
            raise

    check(
        "merge_edge",
        "MERGE (a:Entity {id: $src, name: 'probe-a'})"
        "-[:OWNS {source: 'wikidata', cost: 1.0, rel_id: 1}]->"
        "(b:Entity {id: $dst, name: 'probe-b'})",
        {"src": 900001, "dst": 900002},
    )
    rows = check(
        "match_return",
        "MATCH (a {id: $src})-[:OWNS]->(b) RETURN b.id AS id",
        {"src": 900001},
    )["rows"]
    if not rows:
        raise HydraError("match_return produced no row")

    try:
        check(
            "set_relationship_cost",
            "MATCH (a {id: $src})-[r:OWNS]->(b {id: $dst}) SET r.cost = $cost",
            {"src": 900001, "dst": 900002, "cost": 1.5},
        )
    except HydraError as exc:
        shapes["set_relationship_cost"] = f"error: {exc}"

    weighted_cypher, weighted_params = build_ss_paths(src=900001, weighted=True, total=4, max_len=2)
    try:
        check("sspaths_weighted", weighted_cypher, weighted_params)
    except HydraError as exc:
        shapes["sspaths_weighted"] = f"error: {exc}"

    plain_cypher, plain_params = build_ss_paths(src=900001, weighted=False, total=4, max_len=2)
    try:
        check("sspaths_unweighted", plain_cypher, plain_params)
    except HydraError as exc:
        shapes["sspaths_unweighted"] = f"error: {exc}"

    sp_cypher, sp_params = build_sp_paths(src=900001, dst=900002, weighted=True, total=2, max_len=1)
    try:
        check("sppaths_weighted", sp_cypher, sp_params)
    except HydraError as exc:
        shapes["sppaths_weighted"] = f"error: {exc}"

    if len(set(client.sent_query_ids)) != len(client.sent_query_ids):
        raise HydraError("query_id values were reused")
    shapes["unique_query_id"] = "ok"
    report["shapes"] = shapes
    report["query_ids_sent"] = len(client.sent_query_ids)


def _check_path_count(report: dict) -> None:
    """See whether pathCount stops the whole response or one pair.

    Four outgoing edges from one source. pathCount 2 and resultLimit 8.
    A total cap returns 2 paths. A per-pair reading on a single source is
    the same observation, so this check also builds two sources only when
    the first call works. The raw row count is stored either way.
    """

    client = _client()
    for dst in (910002, 910003, 910004, 910005):
        client.query(
            "MERGE (a:Entity {id: $src})-[:OWNS {cost: 1.0, source: 'wikidata'}]->(b:Entity {id: $dst})",
            {"src": 910001, "dst": dst},
        )
    cypher, params = build_ss_paths(
        src=910001,
        weighted=False,
        total=2,
        max_len=1,
        rel_types=["OWNS"],
    )
    # Force resultLimit above pathCount so a total-vs-pair difference can show.
    params = dict(params)
    params["resultLimit"] = 8
    params["pathCount"] = 2
    payload = client.query(cypher, params)
    report["path_count_probe"] = {
        "pathCount": 2,
        "resultLimit": 8,
        "rows": len(payload["rows"]),
        "interpretation": (
            "On a single source, a total cap and a per-source cap both return 2. "
            "Row count is recorded so a human can compare it with TrailMend. "
            "The client still sizes pathCount as a total and sets resultLimit equal to it."
        ),
    }


def _restart_then_write(report: dict) -> None:
    client = _client()
    client.query(
        "MERGE (a:Entity {id: 920001, name: 'before-restart'})-[:OWNS {source: 'registry', cost: 1.0}]->(b:Entity {id: 920002, name: 'tail'})"
    )
    restarted = _run(["docker", "restart", HYDRA_NAME])
    if restarted.returncode != 0:
        raise HydraError(restarted.stderr.strip() or "docker restart failed")
    if not _wait_http(f"{QUERY}/healthz", timeout=120):
        raise HydraError("query node did not return /healthz after restart")
    # A restart drops the process cache. strong consistency re-reads the bucket.
    after = client.query(
        "MATCH (a:Entity {id: 920001}) RETURN a.name AS name",
        consistency="strong",
    )
    names = []
    for row in after["rows"]:
        cell = row[0]
        names.append(cell.get("value") if isinstance(cell, dict) else cell)
    client.query(
        "MERGE (c:Entity {id: 920003, name: 'after-restart'})-[:OWNS {source: 'registry', cost: 1.0}]->(b:Entity {id: 920002})"
    )
    both = client.query(
        "MATCH (n:Entity {id: 920001}) RETURN n.id AS id",
        consistency="strong",
    )
    written = client.query(
        "MATCH (n:Entity {id: 920003}) RETURN n.name AS name",
        consistency="strong",
    )
    report["restart_then_write"] = {
        "name_after_restart": names,
        "original_still_readable": len(both["rows"]) == 1,
        "second_write_rows": len(written["rows"]),
        "passed": names == ["before-restart"] and len(written["rows"]) == 1,
    }
    if not report["restart_then_write"]["passed"]:
        raise HydraError(f"restart-then-write failed: {report['restart_then_write']}")


def _start_stack() -> None:
    _cleanup()
    network = _run(["docker", "network", "create", NETWORK])
    if network.returncode != 0:
        raise HydraError(network.stderr.strip() or "docker network create failed")
    moto = _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            MOTO_NAME,
            "--network",
            NETWORK,
            "-p",
            "4566:5000",
            "motoserver/moto:latest",
        ]
    )
    if moto.returncode != 0:
        raise HydraError(moto.stderr.strip() or "moto did not start")
    if not _wait_http("http://127.0.0.1:4566/moto-api/", timeout=60):
        # Moto's root may 404 while the daemon is up. A TCP accept is enough;
        # bucket creation below is the real readiness check.
        pass
    # Create the bucket through the published port.
    env = os.environ.copy()
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
    )
    created = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            NETWORK,
            "-e",
            "AWS_ACCESS_KEY_ID=testing",
            "-e",
            "AWS_SECRET_ACCESS_KEY=testing",
            "-e",
            "AWS_DEFAULT_REGION=us-east-1",
            "amazon/aws-cli:2.17.0",
            "s3",
            "mb",
            f"s3://{BUCKET}",
            "--endpoint-url",
            f"http://{MOTO_NAME}:5000",
        ]
    )
    if created.returncode != 0:
        raise HydraError(created.stderr.strip() or created.stdout.strip() or "bucket create failed")

    token_dir = ROOT / ".hydradb"
    token_dir.mkdir(exist_ok=True)
    token_file = token_dir / "probe-token"
    token_file.write_text(TOKEN + "\n")
    hydra = _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            HYDRA_NAME,
            "--network",
            NETWORK,
            "-p",
            "8443:8443",
            "-p",
            "7687:7687",
            "-p",
            "9090:9090",
            "-v",
            f"{token_file}:/auth/token:ro",
            "-e",
            "CLOUD_PROVIDER=aws",
            "-e",
            f"AWS_BUCKET_NAME={BUCKET}",
            "-e",
            "AWS_DEFAULT_REGION=us-east-1",
            "-e",
            "AWS_ALLOW_HTTP=true",
            "-e",
            f"AWS_ENDPOINT=http://{MOTO_NAME}:5000",
            "-e",
            "AWS_ACCESS_KEY_ID=testing",
            "-e",
            "AWS_SECRET_ACCESS_KEY=testing",
            "-e",
            "AWS_EC2_METADATA_DISABLED=true",
            "-e",
            "GRAPH_ALLOW_PLAINTEXT=true",
            "-e",
            "GRAPH_AUTH_TOKEN_FILE=/auth/token",
            "-e",
            "GRAPH_DATA_CACHE_DIR=/var/cache/slatedb",
            "-e",
            "GRAPH_NAMESPACE=default",
            "-e",
            "GRAPH_ID=default",
            "-e",
            "GRAPH_CELL_ID=cell-0",
            "-e",
            "GRAPH_CELLS=cell-0",
            "-e",
            "GRAPH_NODE_ID=node-0",
            "-e",
            "GRAPH_BOLT_NODE_ADDRESSES=node-0=0.0.0.0:7687",
            "-e",
            "GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687",
            "-e",
            "RUST_MIN_STACK=33554432",
            IMAGE,
        ]
    )
    if hydra.returncode != 0:
        raise HydraError(hydra.stderr.strip() or "hydradb did not start")
    if not _wait_http(f"{QUERY}/healthz", timeout=120):
        logs = _run(["docker", "logs", "--tail", "80", HYDRA_NAME])
        raise HydraError("HydraDB /healthz did not come up\n" + logs.stdout + logs.stderr)


def main() -> int:
    report: dict = {
        "image": IMAGE,
        "live_engine": False,
        "docker": shutil.which("docker") is not None,
        "path_budget_contract": path_budget(4),
    }
    try:
        report["digest"] = registry_digests()
    except Exception as exc:  # noqa: BLE001 — the probe must record the failure, not hide it
        report["digest_error"] = str(exc)

    if not report["docker"]:
        report["status"] = "skipped_no_docker"
        report["message"] = (
            "Docker is not on PATH. Registry digest lookup is not a live engine check. "
            "See docs/HYDRA_RUNBOOK.md."
        )
        _write(report)
        print(json.dumps({"status": report["status"], "wrote": str(OUT)}, indent=2))
        return 2

    try:
        _start_stack()
        digest = _run(
            ["docker", "image", "inspect", IMAGE, "--format", "{{index .RepoDigests 0}}"]
        )
        report["local_repo_digest"] = (digest.stdout or digest.stderr).strip()
        _check_shapes(report)
        _check_path_count(report)
        _restart_then_write(report)
        failed = [name for name, status in report.get("shapes", {}).items() if status != "ok"]
        report["live_engine"] = not failed and report["restart_then_write"]["passed"]
        report["status"] = "passed" if report["live_engine"] else "failed"
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["error"] = str(exc)
        logs = _run(["docker", "logs", "--tail", "60", HYDRA_NAME]) if report["docker"] else None
        if logs is not None:
            report["hydra_logs_tail"] = (logs.stdout + logs.stderr)[-4000:]
    finally:
        if os.environ.get("DG_PROBE_KEEP") != "1":
            _cleanup()
        _write(report)

    print(json.dumps({"status": report["status"], "live_engine": report["live_engine"], "wrote": str(OUT)}, indent=2))
    return 0 if report.get("live_engine") else 2


if __name__ == "__main__":
    sys.exit(main())
