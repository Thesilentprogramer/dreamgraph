"""Compact 3D explorer graph. Read-only over the published results.

This does not refit costs or rewrite the benchmark. It samples the cached
claims and attaches the per-iteration costs already stored on the policy
versions.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "data" / "vuln" / "claims.jsonl"
VULN = ROOT / "results" / "vuln_summary.json"
POISON = ROOT / "results" / "vuln_poison.json"
EXPORT = ROOT / "results" / "explorer.json"

CVE_LIMIT = 36
VERSIONS_PER_CVE = 2
VISIBLE_CLAIMS = 3
NODE_CAP = 1600


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _questions(path: Path = CLAIMS) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["cve"], row["version"])
        slot = grouped.setdefault(
            key,
            {
                "cve": row["cve"],
                "repo": row["repo"],
                "version": row["version"],
                "gold": bool(row["gold"]),
                "votes": {},
            },
        )
        slot["votes"][row["source"]] = bool(row["affected"])
    return list(grouped.values())


def _iterations(vuln: dict, poison: dict) -> list[dict]:
    buckets: dict[int, list[dict]] = defaultdict(list)
    for policy in vuln.get("policies") or []:
        buckets[int(policy["iteration"])].append(policy["costs"])
    rolled = {
        int(policy["iteration"])
        for policy in (poison.get("policies") or poison.get("receipts") or [])
        if policy.get("rolled_back")
    }
    drift_iter = int(vuln.get("drift_iter") or 4)
    built = []
    for iteration in range(1, 9):
        rows = buckets.get(iteration) or []
        if not rows:
            continue
        keys = rows[0].keys()
        costs = {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys}
        built.append(
            {
                "iteration": iteration,
                "costs": costs,
                "rollback": iteration in rolled,
                "drift": iteration == drift_iter,
            }
        )
    return built


def _pick(questions: list[dict], vuln: dict) -> list[dict]:
    by_key = {(item["cve"], item["version"]): item for item in questions}
    chosen: list[dict] = []
    seen = set()
    for label in (vuln.get("demo") or {}).get("labels", {}).values():
        if " · " not in label:
            continue
        left, cve = label.split(" · ", 1)
        repo, _, version = left.partition(" ")
        item = by_key.get((cve, version))
        if item and (cve, version) not in seen:
            chosen.append(item)
            seen.add((cve, version))
    by_cve: dict[str, list[dict]] = defaultdict(list)
    for item in questions:
        by_cve[item["cve"]].append(item)
    cves = []
    for cve in by_cve:
        if any(item["cve"] == cve for item in chosen):
            cves.append(cve)
    for cve in sorted(by_cve):
        if cve not in cves:
            cves.append(cve)
        if len(cves) >= CVE_LIMIT:
            break
    for cve in cves:
        versions = sorted(by_cve[cve], key=lambda item: item["version"])
        kept = 0
        for item in versions:
            key = (item["cve"], item["version"])
            if key in seen:
                kept += 1
                continue
            if kept >= VERSIONS_PER_CVE:
                break
            chosen.append(item)
            seen.add(key)
            kept += 1
    return chosen


def build_explorer(claims: Path = CLAIMS, vuln_path: Path = VULN, poison_path: Path = POISON) -> dict:
    questions = _pick(_questions(claims), _load_json(vuln_path))
    vuln = _load_json(vuln_path)
    poison = _load_json(poison_path) if poison_path.exists() else {}
    iterations = _iterations(vuln, poison)
    final_costs = iterations[-1]["costs"] if iterations else {}
    accuracy = {row["source"]: row for row in vuln.get("source_table") or []}
    shifts = (vuln.get("drift") or {}).get("shifts") or {}

    nodes: dict[str, dict] = {}
    links: list[dict] = []

    def add_node(node: dict) -> dict:
        nodes.setdefault(node["id"], node)
        return nodes[node["id"]]

    def add_link(source: str, target: str, kind: str, feed: str | None = None) -> None:
        links.append(
            {
                "id": f"{kind}:{source}->{target}",
                "source": source,
                "target": target,
                "kind": kind,
                "feed": feed,
            }
        )

    for source, cost in sorted(final_costs.items()):
        info = accuracy.get(source) or {}
        add_node(
            {
                "id": f"feed:{source}",
                "type": "feed",
                "name": source,
                "cost": cost,
                "accuracy": info.get("accuracy"),
                "n": info.get("n"),
                "drift": shifts.get(source),
                "cluster": "vuln",
            }
        )

    for item in questions:
        repo, cve, version = item["repo"], item["cve"], item["version"]
        project_id = f"project:{repo}"
        cve_id = f"cve:{cve}"
        version_id = f"version:{repo}:{version}"
        verdict_name = "affected" if item["gold"] else "not affected"
        verdict_id = f"verdict:{verdict_name}"
        add_node({"id": project_id, "type": "project", "name": repo, "cluster": "vuln"})
        add_node({"id": cve_id, "type": "cve", "name": cve, "repo": repo, "cluster": "vuln"})
        add_node(
            {
                "id": version_id,
                "type": "version",
                "name": f"{repo} {version}",
                "repo": repo,
                "version": version,
                "cve": cve,
                "gold": verdict_name,
                "cluster": "vuln",
            }
        )
        add_node(
            {
                "id": verdict_id,
                "type": "verdict",
                "name": verdict_name,
                "cluster": "vuln",
            }
        )
        add_link(project_id, version_id, "has")
        add_link(cve_id, version_id, "about")
        add_link(version_id, verdict_id, "gold")
        votes = sorted(item["votes"])
        visible, hidden = votes[:VISIBLE_CLAIMS], votes[VISIBLE_CLAIMS:]

        def claim_node(feed: str) -> dict:
            vote = "affected" if item["votes"][feed] else "not affected"
            return {
                "id": f"claim:{feed}:{cve}:{version}",
                "type": "claim",
                "name": f"{feed} · {version}",
                "feed": feed,
                "cve": cve,
                "version": version,
                "vote": vote,
                "cluster": "vuln",
            }

        def claim_links(node_id: str, feed: str) -> list[dict]:
            vote_id = f"verdict:{'affected' if item['votes'][feed] else 'not affected'}"
            add_node({"id": vote_id, "type": "verdict", "name": "affected" if item["votes"][feed] else "not affected", "cluster": "vuln"})
            return [
                {"id": f"asserts:{feed}->{node_id}", "source": f"feed:{feed}", "target": node_id, "kind": "asserts", "feed": feed},
                {"id": f"covers:{node_id}->{version_id}", "source": node_id, "target": version_id, "kind": "covers", "feed": feed},
                {"id": f"says:{node_id}->{vote_id}", "source": node_id, "target": vote_id, "kind": "says", "feed": feed},
            ]

        for feed in visible:
            node = claim_node(feed)
            add_node(node)
            for link in claim_links(node["id"], feed):
                links.append(link)
        if hidden:
            group_id = f"group:{cve}:{version}"
            hidden_nodes = []
            hidden_links = []
            for feed in hidden:
                node = claim_node(feed)
                hidden_nodes.append(node)
                hidden_links.extend(claim_links(node["id"], feed))
            add_node(
                {
                    "id": group_id,
                    "type": "group",
                    "name": f"+{len(hidden)} more claims",
                    "count": len(hidden),
                    "cve": cve,
                    "version": version,
                    "repo": repo,
                    "members": hidden_nodes,
                    "memberLinks": hidden_links,
                    "cluster": "vuln",
                }
            )
            add_link(version_id, group_id, "more")

    # A tiny synthetic gadget so those entity types can be toggled on.
    add_node({"id": "company:northwind-1001", "type": "company", "name": "Northwind 1001", "cluster": "synthetic"})
    add_node({"id": "claim:synthetic:long", "type": "claim", "name": "wikidata chain", "feed": "wikidata", "cluster": "synthetic"})
    add_node({"id": "person:holt", "type": "person", "name": "Jordan Holt", "cluster": "synthetic"})
    add_link("company:northwind-1001", "claim:synthetic:long", "owns", "wikidata")
    add_link("claim:synthetic:long", "person:holt", "names", "wikidata")

    node_list = list(nodes.values())
    if len(node_list) > NODE_CAP:
        raise RuntimeError(f"explorer graph has {len(node_list)} nodes; cap is {NODE_CAP}")

    queries = []
    for rel, label in (vuln.get("demo") or {}).get("labels", {}).items():
        if " · " not in label:
            continue
        left, cve = label.split(" · ", 1)
        repo, _, version = left.partition(" ")
        queries.append(
            {
                "rel": int(rel),
                "text": f"is {repo} {version} affected by {cve}?",
                "label": label,
                "versionId": f"version:{repo}:{version}",
                "cveId": f"cve:{cve}",
                "projectId": f"project:{repo}",
            }
        )

    return {
        "generated_from": ["data/vuln/claims.jsonl", "results/vuln_summary.json", "results/vuln_poison.json"],
        "node_count": len(node_list),
        "link_count": len(links),
        "cap": NODE_CAP,
        "iterations": iterations,
        "drift_iter": int(vuln.get("drift_iter") or 4),
        "drift_kind": (vuln.get("drift") or {}).get("kind"),
        "nodes": node_list,
        "links": links,
        "queries": queries,
        "types": ["feed", "cve", "claim", "project", "version", "verdict", "group", "company", "person"],
    }


def write_explorer(path: Path = EXPORT) -> dict:
    document = build_explorer()
    path.write_text(json.dumps(document, separators=(",", ":")) + "\n")
    return document


if __name__ == "__main__":
    document = write_explorer()
    print(document["node_count"], "nodes", document["link_count"], "links", "iters", len(document["iterations"]))
