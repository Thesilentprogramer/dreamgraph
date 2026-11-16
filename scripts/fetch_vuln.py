"""Build the vulnerability slice scored against the Zenodo gold labels.

Gold is the CC BY 4.0 dataset for "Vulnerability-Affected Versions
Identification: How Far Are We?" (Zenodo 16440960). Sources are OSV ecosystem
dumps whose ids or upstream fields name those CVEs, plus NVD ranges from the
public CVE-to-OSV conversion. The 3GB OSV all.zip is not downloaded. Ubuntu's
816MB zip is skipped; Debian covers that family. Only the processed claims
file is written into the repo.

A question is one upstream tag of a gold repository: affected if the tag is in
the manual affected_version list, otherwise not affected. The tag universe is
the set of tags that appear for that repository in the gold file. At most eight
affected and eight unaffected tags are kept per CVE, sampled with seed 0, and
a question is kept only when at least two sources cast a version verdict.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "vuln"
CLAIMS = OUT_DIR / "claims.jsonl"
META = OUT_DIR / "slice.json"

ZENODO_API = "https://zenodo.org/api/records/16440960"
ZENODO_ZIP = "https://zenodo.org/api/records/16440960/files/Dataset.zip/content"
NVD_URL = "https://storage.googleapis.com/cve-osv-conversion/osv-output/{cve}.json"
OSV_URL = "https://storage.googleapis.com/osv-vulnerabilities/{eco}/all.zip"

# Sizes checked on 2026-11-16. Ubuntu is intentionally absent (816 MB).
SOURCES = {
    "debian": "Debian",
    "alpine": "Alpine",
    "redhat": "Red%20Hat",
    "linux": "Linux",
    "alma": "AlmaLinux",
    "opensuse": "openSUSE",
    "suse": "SUSE",
    "mageia": "Mageia",
    "rocky": "Rocky%20Linux",
}

CACHE = Path("/tmp/dreamgraph-vuln")
POS_CAP = 3
NEG_CAP = 3
CVE_CAP_PER_REPO = 40
SAMPLE_SEED = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    print(f"download {url}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def digits(value: str | None) -> tuple[int, ...] | None:
    """Numeric version key. Git commit ids are not versions."""

    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,}", text):
        return None
    text = re.sub(r"^\d+:", "", text)
    text = text.replace("_", ".")
    nums = tuple(int(part) for part in re.findall(r"\d+", text)[:6])
    return nums or None


def _cmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def in_events(version: tuple[int, ...], events: list[dict]) -> bool | None:
    affected = False
    saw = False
    for event in events:
        if "introduced" in event:
            bound = digits(str(event["introduced"]))
            if bound is None:
                continue
            saw = True
            affected = _cmp(version, bound) >= 0
        elif "fixed" in event:
            bound = digits(str(event["fixed"]))
            if bound is None:
                continue
            saw = True
            if _cmp(version, bound) >= 0:
                affected = False
        elif "last_affected" in event:
            bound = digits(str(event["last_affected"]))
            if bound is None:
                continue
            saw = True
            if _cmp(version, bound) > 0:
                affected = False
    return affected if saw else None


def verdict_of(doc: dict, version: tuple[int, ...]) -> bool | None:
    explicit = False
    hit = False
    ranged: bool | None = None
    for affected in doc.get("affected") or []:
        for raw in affected.get("versions") or []:
            parsed = digits(raw)
            if parsed is None:
                continue
            explicit = True
            if parsed == version:
                hit = True
        for item in affected.get("ranges") or []:
            extracted = (item.get("database_specific") or {}).get("extracted_events") or []
            for block in extracted:
                if block.get("source") == "CPE_RANGE" and block.get("range"):
                    answer = in_events(version, block["range"])
                    if answer is not None:
                        ranged = answer if ranged is None else (ranged or answer)
            answer = in_events(version, item.get("events") or [])
            if answer is not None:
                ranged = answer if ranged is None else (ranged or answer)
    if hit:
        return True
    if ranged is not None:
        return ranged
    if explicit:
        return False
    return None


def cve_ids(doc: dict) -> set[str]:
    blob = " ".join(
        [
            str(doc.get("id") or ""),
            " ".join(doc.get("upstream") or []) if isinstance(doc.get("upstream"), list) else str(doc.get("upstream") or ""),
            " ".join(doc.get("aliases") or []),
        ]
    )
    return set(re.findall(r"CVE-\d{4}-\d+", blob))


def load_gold(dataset_zip: Path) -> dict:
    with zipfile.ZipFile(dataset_zip) as archive:
        return json.loads(archive.read("Dataset.json"))


def load_osv(path: Path, gold_ids: set[str]) -> dict[str, list[dict]]:
    bucket: dict[str, list[dict]] = defaultdict(list)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json"):
                continue
            doc = json.loads(archive.read(name))
            for cve in cve_ids(doc) & gold_ids:
                bucket[cve].append(doc)
    return bucket


def load_nvd(cves: list[str]) -> dict[str, list[dict]]:
    dest = CACHE / "nvd"
    dest.mkdir(parents=True, exist_ok=True)

    def one(cve: str) -> tuple[str, dict | None]:
        path = dest / f"{cve}.json"
        if not path.exists() or path.stat().st_size == 0:
            try:
                urllib.request.urlretrieve(NVD_URL.format(cve=cve), path)
            except Exception:
                return cve, None
        try:
            return cve, json.loads(path.read_text())
        except Exception:
            return cve, None

    found: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = [pool.submit(one, cve) for cve in cves]
        done = 0
        for future in as_completed(futures):
            cve, doc = future.result()
            done += 1
            if doc:
                found[cve] = [doc]
            if done % 200 == 0:
                print(f"nvd {done}/{len(cves)}", flush=True)
    print(f"nvd records {len(found)}", flush=True)
    return found


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    dataset_zip = CACHE / "Dataset.zip"
    _download(ZENODO_ZIP, dataset_zip)
    gold = load_gold(dataset_zip)
    gold_ids = set(gold)
    feeds: dict[str, dict[str, list[dict]]] = {}
    checksums = {"zenodo_dataset_zip": _sha256(dataset_zip)}
    for source, eco in SOURCES.items():
        path = CACHE / f"{source}.zip"
        _download(OSV_URL.format(eco=eco), path)
        checksums[source] = _sha256(path)
        feeds[source] = load_osv(path, gold_ids)
        print(f"{source} cves {len(feeds[source])}", flush=True)
    feeds["nvd"] = load_nvd(sorted(gold_ids))

    repo_versions: dict[str, set[str]] = defaultdict(set)
    for row in gold.values():
        repo_versions[row["repo"]].update(row.get("affected_version") or [])

    rng = random.Random(SAMPLE_SEED)
    by_repo: dict[str, list[str]] = defaultdict(list)
    for cve in sorted(gold):
        by_repo[gold[cve]["repo"]].append(cve)
    chosen_cves = []
    for repo in sorted(by_repo):
        cves = by_repo[repo]
        rng.shuffle(cves)
        chosen_cves.extend(cves[:CVE_CAP_PER_REPO])
    chosen_cves = set(chosen_cves)
    rows = []
    questions = 0
    for cve in sorted(chosen_cves):
        record = gold[cve]
        repo = record["repo"]
        affected = set(record.get("affected_version") or [])
        universe = sorted(repo_versions[repo])
        positives = [version for version in universe if version in affected]
        negatives = [version for version in universe if version not in affected]
        rng.shuffle(positives)
        rng.shuffle(negatives)
        sample = [(version, True) for version in positives[:POS_CAP]] + [
            (version, False) for version in negatives[:NEG_CAP]
        ]
        for version, label in sample:
            parsed = digits(version)
            if parsed is None:
                continue
            votes = {}
            modified = []
            for source, bucket in feeds.items():
                docs = bucket.get(cve) or []
                answer = None
                stamp = None
                for doc in docs:
                    vote = verdict_of(doc, parsed)
                    if vote is None:
                        continue
                    answer = vote if answer is None else (answer or vote)
                    if doc.get("modified"):
                        stamp = max(stamp or "", doc["modified"])
                if answer is None:
                    continue
                votes[source] = answer
                if stamp:
                    modified.append(stamp)
            if len(votes) < 2:
                continue
            questions += 1
            modified.sort()
            mid = modified[len(modified) // 2] if modified else ""
            for source, vote in sorted(votes.items()):
                rows.append(
                    {
                        "affected": bool(vote),
                        "cve": cve,
                        "gold": bool(label),
                        "modified": mid,
                        "repo": repo,
                        "source": source,
                        "version": version,
                    }
                )
    rows.sort(key=lambda row: (row["cve"], row["version"], row["source"]))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    CLAIMS.write_text(payload)
    checksums["claims_jsonl"] = hashlib.sha256(payload.encode()).hexdigest()
    meta = {
        "questions": questions,
        "rows": len(rows),
        "cves": len({row["cve"] for row in rows}),
        "sources": sorted({row["source"] for row in rows}),
        "gold_cves": len(gold),
        "zenodo": "https://doi.org/10.5281/zenodo.16440960",
        "license": "CC BY 4.0",
        "checksums": checksums,
        "sampling": {
            "positives_per_cve": POS_CAP,
            "negatives_per_cve": NEG_CAP,
            "cves_per_repo": CVE_CAP_PER_REPO,
            "seed": SAMPLE_SEED,
            "min_sources": 2,
        },
        "ghsa": (
            "The GitHub Advisory API lists these CVEs but returns no package version "
            "ranges for the sampled records, so GHSA is not a version-level voter."
        ),
        "ubuntu": "Skipped. The Ubuntu OSV zip is 816 MB; Debian is the Debian-family feed in this slice.",
        "kev": "CISA KEV has no version ranges, so it is not a voter on tag-level questions.",
    }
    META.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: meta[k] for k in ("questions", "rows", "cves", "sources")}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(exc, file=sys.stderr)
        raise
