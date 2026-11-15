# HydraDB runbook

DreamGraph talks to the open-source engine image `ghcr.io/hydra-db/hydradb:0.4.0`. The query node listens on **8443** (HTTP), **7687** (Bolt), and **9090** (admin). The DreamGraph app listens on **8000**. Do not bind the engine to 8000.

Durable graph state is a bucket. The container's `/var/cache/slatedb` directory is a disposable cache. `CLOUD_PROVIDER=local` is not a supported DreamGraph layout: TrailMend lost the graph on restart when the only copy sat on local disk.

## Native process, no Docker

`CLOUD_PROVIDER=local` answers the create-only probe and then rejects updates (`PutMode::Update` is not implemented on the local filesystem). The live node therefore uses moto.

```bash
python scripts/extract_hydradb_image.py    # ghcr.io token, amd64 layers, unpack to ~/hydradb-root
pip install 'moto[server]'
.venv/bin/moto_server -H 0.0.0.0 -p 4566    # create bucket dreamgraph
bash scripts/run_hydradb_native.sh
python scripts/probe_hydradb.py             # exit 0 and live_engine true
```

`graph-node` is the image entrypoint. `libgraphblas.so.7` comes from the image via `LD_LIBRARY_PATH`. The host glibc is 2.39, which matches the Ubuntu 24.04 runtime in the image, so the system loader is enough.

## What this environment already recorded

`make probe` always asks GHCR for the manifest index digest and writes `results/probe.json`.

- Exit **0** means `live_engine: true`. Every Cypher shape, the path-count measurement, and the restart-then-write check passed against a running node.
- Exit **2** means the engine was **not** verified. A registry digest alone is not a pass.

The machine that produced the committed `results/probe.json` did not have Docker. Treat `live_engine: false` as the truth until you re-run the probe yourself.

## Live probe

Requirements: Docker, and the ability to pull `ghcr.io/hydra-db/hydradb:0.4.0` and `motoserver/moto`.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/probe_hydradb.py
```

The script:

1. Records the registry index digest and the `linux/amd64` and `linux/arm64` manifest digests.
2. Starts moto on the `dreamgraph-probe` network and creates bucket `dreamgraph-probe`.
3. Starts `graph-node` with `CLOUD_PROVIDER=aws`, `AWS_ALLOW_HTTP=true`, `AWS_ENDPOINT=http://dreamgraph-probe-moto:5000`, plaintext listeners, and `RUST_MIN_STACK=33554432`.
4. Sends `MERGE`, `MATCH`, `MATCH … SET` on a relationship cost, weighted and unweighted `algo.SSpaths`, and weighted `algo.SPpaths`. Every body has a new `query_id`, `cell_id`, and a path budget from `path_budget()` (`pathCount` and `resultLimit` share one total).
5. Asks `algo.SSpaths` for `pathCount: 2` with `resultLimit: 8` and records the row count. The client keeps treating `pathCount` as a **total** cap regardless of that single-source measurement; the raw count is there so you can see the engine's answer.
6. Restarts the HydraDB container, reads the pre-restart node with `consistency: "strong"`, writes a second node, and reads both.
7. Removes the containers unless `DG_PROBE_KEEP=1`.

Then open `results/probe.json`. `"live_engine": true` is the only success flag.

## Compose stack (app + engine + moto)

From a machine with Docker:

```bash
docker compose up --build
```

- App: `http://127.0.0.1:8000`
- HydraDB health: `http://127.0.0.1:8443/healthz`
- Moto: `http://127.0.0.1:4566`

Run the benchmark against the engine only after the probe passed:

```bash
DG_BACKEND=hydradb DG_HYDRA_URL=http://127.0.0.1:8443 make bench
```

If the engine is down, that command **fails**. It does not silently score the in-process graph and label it HydraDB. The default `make bench` is the memory backend and says so in `results/summary.json`.

## Image digest by hand

```bash
docker pull ghcr.io/hydra-db/hydradb:0.4.0
docker image inspect ghcr.io/hydra-db/hydradb:0.4.0 --format '{{index .RepoDigests 0}}'
```

Compare it with `results/probe.json` → `digest.index_digest` and `digest.platforms["linux/amd64"]`. A tag match without a digest match is not the image this repo recorded.

## Railway

See `README.md` and `deploy/hydradb.railway.toml`. Use a Railway bucket. Set `AWS_ENDPOINT` to the bucket's S3 endpoint, `AWS_ALLOW_HTTP` to the value the endpoint's scheme requires, and mount the auth token from a secret. The public app service uses `PORT` (Railway injects it) and must listen on `0.0.0.0`. HydraDB's public domain, if you expose one, targets **8443**, with the bearer token required on `/v1/graphs/default/query`. `/healthz` does not require the token.

## Failure notes

| Symptom | What it usually means |
|---|---|
| HTTP 422 and no `error` key | `cell_id` missing |
| HTTP 500 `internal` | wrong `cell_id`, or the node cannot read the bucket |
| `/readyz` connection refused | admin port is 9090, not 8443 |
| Empty graph after restart | the node was on `CLOUD_PROVIDER=local` or a new empty bucket |
| `pathCount` returned one path | the default is 1; set it explicitly |
| Cursor skipped a page | `query_id` was reused, or a page was retried. Send a new id and do not retry a cursor |
| `resultLimit must be greater than zero` | do not send 0; there is no "unlimited" value |
