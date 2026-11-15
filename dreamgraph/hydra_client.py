"""Thin HydraDB HTTP client.

Path budgets follow the TrailMend measurement: ``pathCount`` is a total cap,
and every call also sets ``resultLimit`` to that same total. Each request
carries a new ``query_id``. Tests inject a transport; nothing here opens a
socket unless ``HttpTransport`` is constructed.
"""

from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from dreamgraph.config import REL_TYPE, SOURCES


class HydraError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


Transport = Callable[[dict[str, Any]], dict[str, Any]]


def path_budget(total: int) -> dict[str, int]:
    """Return the total path cap shared by ``pathCount`` and ``resultLimit``.

    ``total`` is the whole response budget. Do not multiply it by the number
    of source/target pairs. ``resultLimit`` must be greater than zero.
    """

    if total <= 0:
        raise ValueError("resultLimit must be greater than zero")
    return {"pathCount": total, "resultLimit": total}


def _cypher_string_list(values: list[str]) -> str:
    parts = []
    for value in values:
        if not value.replace("_", "").isalnum():
            raise ValueError(f"refusing to inline relationship type {value!r}")
        parts.append("'" + value + "'")
    return "[" + ", ".join(parts) + "]"


def build_ss_paths(
    *,
    src: int,
    weighted: bool,
    total: int = 4,
    max_len: int = 2,
    rel_types: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    budget = path_budget(total)
    types = rel_types or [REL_TYPE[source] for source in SOURCES]
    weight = ",\n  weightProp: 'cost'" if weighted else ""
    cypher = (
        "CALL algo.SSpaths({\n"
        "  sourceNode: $src,\n"
        f"  relTypes: {_cypher_string_list(types)},\n"
        "  relDirection: 'outgoing',\n"
        "  maxLen: $maxLen,\n"
        "  pathCount: $pathCount,\n"
        "  resultLimit: $resultLimit"
        f"{weight}\n"
        "})\n"
        "YIELD path, pathWeight\n"
        "RETURN path, pathWeight"
    )
    params = {
        "src": src,
        "maxLen": max_len,
        "pathCount": budget["pathCount"],
        "resultLimit": budget["resultLimit"],
    }
    return cypher, params


def build_sp_paths(
    *,
    src: int,
    dst: int,
    weighted: bool,
    total: int = 4,
    max_len: int = 2,
    rel_types: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    budget = path_budget(total)
    types = rel_types or [REL_TYPE[source] for source in SOURCES]
    weight = ",\n  weightProp: 'cost'" if weighted else ""
    cypher = (
        "CALL algo.SPpaths({\n"
        "  sourceNode: $src,\n"
        "  targetNode: $dst,\n"
        f"  relTypes: {_cypher_string_list(types)},\n"
        "  relDirection: 'outgoing',\n"
        "  maxLen: $maxLen,\n"
        "  pathCount: $pathCount,\n"
        "  resultLimit: $resultLimit"
        f"{weight}\n"
        "})\n"
        "YIELD path, pathWeight\n"
        "RETURN path, pathWeight"
    )
    params = {
        "src": src,
        "dst": dst,
        "maxLen": max_len,
        "pathCount": budget["pathCount"],
        "resultLimit": budget["resultLimit"],
    }
    return cypher, params


def unwrap_property(value: Any) -> Any:
    """Path properties are tagged ``{"String": "x"}``; other cells are not."""

    if isinstance(value, dict) and len(value) == 1:
        return next(iter(value.values()))
    return value


def unwrap_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    return {key: unwrap_property(val) for key, val in (properties or {}).items()}


def parse_path_cell(cell: dict[str, Any]) -> dict[str, Any]:
    if cell.get("type") != "path":
        raise HydraError(f"expected a path cell, got {cell.get('type')}")
    value = cell.get("value") or {}
    nodes = []
    for node in value.get("nodes") or []:
        nodes.append(
            {
                "id": node.get("id"),
                "labels": list(node.get("labels") or []),
                "properties": unwrap_properties(node.get("properties")),
            }
        )
    relationships = []
    for rel in value.get("relationships") or []:
        relationships.append(
            {
                "type": rel.get("edge_type"),
                "src": rel.get("src"),
                "dst": rel.get("dst"),
                "properties": unwrap_properties(rel.get("properties")),
            }
        )
    return {"nodes": nodes, "relationships": relationships}


def cell_value(cell: Any) -> Any:
    if not isinstance(cell, dict):
        return cell
    if cell.get("type") == "null":
        return None
    if cell.get("type") == "path":
        return parse_path_cell(cell)
    return cell.get("value")


class HydraClient:
    def __init__(self, transport: Transport, cell_id: str = "cell-0"):
        self.transport = transport
        self.cell_id = cell_id
        self.sent_query_ids: list[str] = []

    def query(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
        *,
        consistency: str = "causal",
    ) -> dict[str, Any]:
        query_id = str(uuid.uuid4())
        self.sent_query_ids.append(query_id)
        body = {
            "cell_id": self.cell_id,
            "query_id": query_id,
            "query": cypher,
            "parameters": parameters or {},
            "consistency": consistency,
        }
        payload = self.transport(body)
        if not isinstance(payload, dict):
            raise HydraError("HydraDB returned a non-object payload", payload=payload)
        if "error" in payload:
            err = payload["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise HydraError(message or "HydraDB error", payload=payload)
        if "rows" not in payload:
            raise HydraError(
                "HydraDB response had neither rows nor error (often HTTP 422)",
                payload=payload,
            )
        return payload

    def rows(self, cypher: str, parameters: dict[str, Any] | None = None) -> list[list[Any]]:
        payload = self.query(cypher, parameters)
        decoded = []
        for row in payload["rows"]:
            decoded.append([cell_value(cell) for cell in row])
        return decoded

    def cheapest_paths_from(self, src: int, *, weighted: bool, total: int = 4) -> list[dict[str, Any]]:
        cypher, params = build_ss_paths(src=src, weighted=weighted, total=total)
        found = []
        for row in self.rows(cypher, params):
            found.append({"path": row[0], "path_weight": row[1]})
        return found


class HttpTransport:
    """POST a query body to a live HydraDB. Used by the probe and ``DG_BACKEND=hydradb``."""

    def __init__(self, base_url: str, token: str, graph_id: str = "default", timeout: float = 30.0):
        self.url = f"{base_url.rstrip('/')}/v1/graphs/{graph_id}/query"
        self.token = token
        self.timeout = timeout

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode()
        request = urllib.request.Request(
            self.url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            status = exc.code
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"message": raw}
            if isinstance(payload, dict) and "error" not in payload and "rows" not in payload:
                raise HydraError(raw or f"HTTP {status}", status=status, payload=payload) from exc
            if isinstance(payload, dict):
                payload.setdefault("_http_status", status)
            return payload if isinstance(payload, dict) else {"error": {"message": raw}}
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise HydraError(f"non-JSON response HTTP {status}", status=status) from exc
        if isinstance(payload, dict):
            payload.setdefault("_http_status", status)
        return payload
