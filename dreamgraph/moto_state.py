"""Snapshot and restore the moto bucket HydraDB uses as object storage.

Render's filesystem is ephemeral, and the free plan has no persistent disk.
``DG_STATE_DIR`` (default ``/var/lib/dreamgraph/state``) is where a mounted
disk would keep the bucket. An empty directory is a no-op. The Blueprint
does not attach a disk and does not change the instance plan.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import boto3

from dreamgraph.config import S3_ACCESS_KEY, S3_BUCKET, S3_REGION, S3_SECRET_KEY


def state_dir() -> Path:
    return Path(os.environ.get("DG_STATE_DIR", "/var/lib/dreamgraph/state"))


def client_from_env():
    endpoint = os.environ.get("AWS_ENDPOINT") or os.environ.get("DG_S3_ENDPOINT") or "http://127.0.0.1:4566"
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_DEFAULT_REGION", S3_REGION),
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", S3_ACCESS_KEY),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", S3_SECRET_KEY),
    )


def snapshot_bucket(client, bucket: str, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    keys = []
    token = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents") or []:
            keys.append(item["Key"])
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    manifest = []
    for index, key in enumerate(sorted(keys)):
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        name = f"{index:06d}.bin"
        (directory / name).write_bytes(body)
        manifest.append({"key": key, "file": name})
    (directory / "manifest.json").write_text(json.dumps(manifest))
    # Drop files left from a larger previous snapshot.
    keep = {item["file"] for item in manifest} | {"manifest.json"}
    for child in directory.iterdir():
        if child.name not in keep:
            child.unlink()
    return len(manifest)


def restore_bucket(client, bucket: str, directory: Path) -> int:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return 0
    manifest = json.loads(manifest_path.read_text())
    existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)
    restored = 0
    for item in manifest:
        blob = (directory / item["file"]).read_bytes()
        client.put_object(Bucket=bucket, Key=item["key"], Body=blob)
        restored += 1
    return restored


def main(argv: list[str] | None = None) -> None:
    command = (argv or sys.argv[1:])[:1]
    action = command[0] if command else "snapshot"
    bucket = os.environ.get("AWS_BUCKET_NAME", S3_BUCKET)
    directory = state_dir()
    if action == "watch":
        while True:
            try:
                count = snapshot_bucket(client_from_env(), bucket, directory)
                print(f"moto snapshot {count} objects", flush=True)
            except Exception as exc:  # noqa: BLE001 — persistence must not kill the node
                print(f"moto snapshot skipped: {exc}", flush=True)
            time.sleep(int(os.environ.get("DG_STATE_INTERVAL", "120")))
        return
    try:
        client = client_from_env()
        if action == "restore":
            count = restore_bucket(client, bucket, directory)
            print(f"moto restore {count} objects", flush=True)
        elif action == "snapshot":
            count = snapshot_bucket(client, bucket, directory)
            print(f"moto snapshot {count} objects", flush=True)
        else:
            raise SystemExit(f"unknown moto state command {action}")
    except Exception as exc:  # noqa: BLE001
        print(f"moto {action} skipped: {exc}", flush=True)
        raise SystemExit(0) from exc


if __name__ == "__main__":
    main()
