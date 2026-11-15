#!/bin/bash
# One container: moto, graph-node 0.4.0, and the FastAPI dashboard.
# Render injects PORT. HydraDB stays on 8443 inside the container.
set -euo pipefail

mkdir -p /var/lib/dreamgraph /var/cache/slatedb
TOKEN="${HYDRADB_AUTH_TOKEN:-local-development-token-32-bytes}"
umask 077
printf '%s\n' "$TOKEN" > /var/lib/dreamgraph/auth-token
export DG_HYDRA_TOKEN="$TOKEN"
export DG_HYDRA_URL="${DG_HYDRA_URL:-http://127.0.0.1:8443}"
export DG_SEED_ON_BOOT="${DG_SEED_ON_BOOT:-1}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-testing}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-testing}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_EC2_METADATA_DISABLED=true

moto_server -H 127.0.0.1 -p 4566 >/tmp/moto.log 2>&1 &

python3 - << 'PY'
import os
import time
import urllib.request

import boto3

for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:4566/", timeout=1)
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("moto did not listen on 4566")

client = boto3.client(
    "s3",
    region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    endpoint_url="http://127.0.0.1:4566",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)
names = {bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])}
if "dreamgraph" not in names:
    client.create_bucket(Bucket="dreamgraph")
PY

export CLOUD_PROVIDER=aws
export AWS_BUCKET_NAME="${AWS_BUCKET_NAME:-dreamgraph}"
export AWS_ALLOW_HTTP=true
export AWS_ENDPOINT=http://127.0.0.1:4566
export GRAPH_NAMESPACE=default
export GRAPH_ID=default
export GRAPH_CELL_ID=cell-0
export GRAPH_CELLS=cell-0
export GRAPH_NODE_ID=node-0
export GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687
export GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687
export GRAPH_DATA_CACHE_DIR=/var/cache/slatedb
export GRAPH_DATA_CACHE_BYTES="${GRAPH_DATA_CACHE_BYTES:-67108864}"
export GRAPH_AUTH_TOKEN_FILE=/var/lib/dreamgraph/auth-token
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432
export GRAPH_USAGE_REPORT_ENABLED=false
export RUST_LOG="${RUST_LOG:-info}"

/usr/local/bin/graph-node >/tmp/graph-node.log 2>&1 &

python3 - << 'PY'
import time
import urllib.request

for _ in range(90):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8443/healthz", timeout=2) as response:
            if response.status == 200:
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        time.sleep(1)
raise SystemExit("graph-node did not open /healthz")
PY

exec uvicorn dreamgraph.api:app --host 0.0.0.0 --port "${PORT:-8000}"
