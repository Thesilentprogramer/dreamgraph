#!/usr/bin/env python3
"""Pull ghcr.io/hydra-db/hydradb:0.4.0 without Docker and unpack the rootfs.

Uses the anonymous GHCR token, the linux/amd64 manifest, and the layer blobs.
The runtime image is Ubuntu 24.04. graph-node is /usr/local/bin/graph-node and
needs libgraphblas from the image via LD_LIBRARY_PATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

IMAGE_REPO = "hydra-db/hydradb"
TAG = "0.4.0"
ROOT = os.environ.get("DG_HYDRA_ROOT", os.path.expanduser("~/hydradb-root"))


def token() -> str:
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{IMAGE_REPO}:pull"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode())["token"]


def get_json(url: str, bearer: str, accept: str) -> tuple[dict, str | None]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}", "Accept": accept})
    with urllib.request.urlopen(request, timeout=60) as response:
        digest = response.headers.get("Docker-Content-Digest")
        return json.loads(response.read().decode()), digest


def download(url: str, bearer: str, dest: str) -> None:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(request, timeout=180) as response, open(dest, "wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def main() -> int:
    bearer = token()
    index, index_digest = get_json(
        f"https://ghcr.io/v2/{IMAGE_REPO}/manifests/{TAG}",
        bearer,
        "application/vnd.oci.image.index.v1+json",
    )
    amd = next(
        item["digest"]
        for item in index["manifests"]
        if (item.get("platform") or {}).get("architecture") == "amd64"
        and (item.get("platform") or {}).get("os") == "linux"
    )
    manifest, _ = get_json(
        f"https://ghcr.io/v2/{IMAGE_REPO}/manifests/{amd}",
        bearer,
        "application/vnd.oci.image.manifest.v1+json",
    )
    os.makedirs(ROOT, exist_ok=True)
    blob_dir = os.path.join(ROOT, ".blobs")
    os.makedirs(blob_dir, exist_ok=True)
    for layer in manifest["layers"]:
        digest = layer["digest"].split(":", 1)[1]
        path = os.path.join(blob_dir, digest)
        if not os.path.exists(path) or os.path.getsize(path) != layer["size"]:
            print(f"fetch {digest[:12]} ({layer['size'] / 1e6:.1f} MB)", flush=True)
            download(f"https://ghcr.io/v2/{IMAGE_REPO}/blobs/{layer['digest']}", bearer, path)
        print(f"extract {digest[:12]}", flush=True)
        subprocess.check_call(["tar", "-C", ROOT, "-xzf", path])
    binary = os.path.join(ROOT, "usr/local/bin/graph-node")
    if not os.path.isfile(binary):
        print("graph-node missing after extract", file=sys.stderr)
        return 1
    subprocess.check_call(["chmod", "+x", binary])
    print(json.dumps({"root": ROOT, "binary": binary, "index_digest": index_digest, "amd64": amd}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
