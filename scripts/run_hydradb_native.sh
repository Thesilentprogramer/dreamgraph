#!/usr/bin/env bash
# Run the extracted graph-node against moto on 127.0.0.1:4566.
# CLOUD_PROVIDER=local rejects object updates (PutMode::Update), so the live
# node uses S3. Docker is not required.
set -euo pipefail

ROOT="${DG_HYDRA_ROOT:-$HOME/hydradb-root}"
BIN="$ROOT/usr/local/bin/graph-node"
DATA="${DG_HYDRA_DATA:-$HOME/hydradb-data}"
TOKEN_FILE="$DATA/auth-token"
CACHE="$DATA/cache"
MOTO_PORT="${DG_MOTO_PORT:-4566}"
BUCKET="${DG_S3_BUCKET:-dreamgraph}"

if [[ ! -x "$BIN" ]]; then
  echo "missing $BIN — run scripts/extract_hydradb_image.py" >&2
  exit 1
fi

mkdir -p "$CACHE"
if [[ ! -f "$TOKEN_FILE" ]]; then
  printf '%s\n' 'local-development-token-32-bytes' > "$TOKEN_FILE"
fi

export LD_LIBRARY_PATH="$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CLOUD_PROVIDER=aws
export AWS_BUCKET_NAME="$BUCKET"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_ALLOW_HTTP=true
export AWS_ENDPOINT="${AWS_ENDPOINT:-http://127.0.0.1:${MOTO_PORT}}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-testing}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-testing}"
export AWS_EC2_METADATA_DISABLED=true
export GRAPH_NAMESPACE=default
export GRAPH_ID=default
export GRAPH_CELL_ID=cell-0
export GRAPH_CELLS=cell-0
export GRAPH_NODE_ID=node-0
export GRAPH_BOLT_NODE_ADDRESSES="${GRAPH_BOLT_NODE_ADDRESSES:-node-0=127.0.0.1:7687}"
export GRAPH_ADVERTISED_BOLT_ADDR="${GRAPH_ADVERTISED_BOLT_ADDR:-127.0.0.1:7687}"
export GRAPH_DATA_CACHE_DIR="$CACHE"
export GRAPH_AUTH_TOKEN_FILE="$TOKEN_FILE"
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432
export GRAPH_USAGE_REPORT_ENABLED=false
export RUST_LOG="${RUST_LOG:-info}"

exec "$BIN"
