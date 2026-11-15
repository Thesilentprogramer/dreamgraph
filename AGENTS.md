# DreamGraph agent notes

DreamGraph is a HydraDB hackathon Track 1 system: a multi-vendor entity graph whose path costs get refit from reviewer feedback. HydraDB does the weighted path search (`algo.SSpaths` / `algo.SPpaths`). The learner never writes a gold edge cost of 0, and there is no SHORTCUT stage.

These notes already include the three stress-test revisions (drift and windowed replay, honest baselines, storage and engine facts). Follow them even when an upstream doc disagrees; the Phase 0 probe is how a live `0.4.0` node confirms the engine.

## Revisions from the stress test

1. **Source drift and windowed replay are the headline.** `python seed.py --drift` swaps the `wikidata` and `scraper` source labels on relations whose `rel_id` is greater than or equal to 15. The swap fires at iteration `DG_DRIFT_ITER` (default **4**). After each iteration the learner refits on only the last `DG_WINDOW` questions (default **100**). Do not add a SHORTCUT pass. Do not pin gold edges to a zero or near-zero cost.
2. **Baselines stay honest.** Report all of: unweighted graph, hand-set source costs, one-shot static fit, the same learner over plain Python dicts, greedy online updates with no replay and no guard, BM25 over source labels, and a model frozen after iteration 3. Evaluation is **300** held-out questions, **3** seeds, stratified bootstrap confidence intervals, and a drift marker on the chart. If the dict learner matches DreamGraph, say so.
3. **Storage and HydraDB facts.** Durable state is S3-compatible object storage: [moto](https://github.com/getmoto/moto) locally, a Railway bucket in production. Local disk is cache or an export, never the source of truth. Ship a restart-then-write probe. Send a **unique `query_id` on every request**. Set **`resultLimit`** on every path call. The public app binds **`0.0.0.0:8000`** (`PORT` overrides the port, not the bind address). Record the image digest, not only the tag. **`pathCount` is a total cap** (TrailMend). It is not a per-pair budget you multiply by the number of pairs.

## TrailMend spikes to respect

TrailMend's runs are why the rules above are strict:

- Treating `pathCount` as per-pair and multiplying by the pair count blew the result size up against the real cap. Size `pathCount` as the **total** number of paths you are willing to accept, and set `resultLimit` to that same total (`resultLimit: 0` is rejected). Upstream `USING-HYDRADB.md` currently says `pathCount` is per pair and `resultLimit` is the total cap. DreamGraph follows the measured total-cap behavior for **both** knobs. The probe records what `0.4.0` actually returns.
- A node that looked durable on local disk came back empty after a restart, because the disk was cache. Object storage is the source of truth. The probe writes, restarts the query node against the same bucket, reads, then writes again.
- Reusing a `query_id` collided with an open cursor and skipped or repeated pages. Generate a new UUID per request, including the first page.
- A missing `resultLimit` let a path procedure run out to the server's vertex budget. Always set it.
- The tag `ghcr.io/hydra-db/hydradb:0.4.0` can move. Record the registry digest (index and the `linux/amd64` manifest). A pulled image's `RepoDigests` entry is the confirmation step when Docker is present.

## Image

| | |
|---|---|
| Image | `ghcr.io/hydra-db/hydradb:0.4.0` |
| Entrypoint | `graph-node` (the published runtime stage) |
| Query HTTP | `0.0.0.0:8443` — `GET /healthz`, `POST /v1/graphs/{graph}/query` |
| Bolt | `0.0.0.0:7687` |
| Admin | `0.0.0.0:9090` — `GET /readyz` (empty 200), `GET /metrics` |

Do not point HydraDB's HTTP port at 8000. The DreamGraph app owns 8000; the engine keeps 8443 so `/healthz` and the query API stay where clients and the probe expect them. `GET /healthz` on 9090 is 404. `GET /readyz` on 8443 is not readiness.

Token file default: `local-development-token-32-bytes`. Bolt password is the token; username is `neo4j`. `cell_id` is mandatory on every HTTP body (`cell-0`). A wrong cell is an opaque HTTP 500. A missing `cell_id` is HTTP 422 with neither `rows` nor `error`.

## Object storage

HydraDB:

```text
CLOUD_PROVIDER=aws
AWS_BUCKET_NAME=dreamgraph
AWS_DEFAULT_REGION=us-east-1
AWS_ALLOW_HTTP=true
AWS_ENDPOINT=http://moto:5000
AWS_ACCESS_KEY_ID=testing
AWS_SECRET_ACCESS_KEY=testing
AWS_EC2_METADATA_DISABLED=true
GRAPH_ALLOW_PLAINTEXT=true
GRAPH_AUTH_TOKEN_FILE=/auth/token
GRAPH_DATA_CACHE_DIR=/var/cache/slatedb
GRAPH_NAMESPACE=default
GRAPH_ID=default
GRAPH_CELL_ID=cell-0
GRAPH_CELLS=cell-0
GRAPH_NODE_ID=node-0
GRAPH_BOLT_NODE_ADDRESSES=node-0=0.0.0.0:7687
RUST_MIN_STACK=33554432
```

`CLOUD_PROVIDER=local` is not a valid DreamGraph deployment. The cache directory is disposable.

DreamGraph's own benchmark artifacts (policy versions, the summary the chart reads) are written to the same kind of bucket under `results/summary.json`. `make bench` uses in-process moto and then exports a copy to `./results/` so the dashboard and git have a file. The export is labeled `storage: s3` plus `export_path` in the JSON. The API serves that export unless `DG_S3_ENDPOINT` is set, in which case it reads the bucket.

## Cypher shapes we actually send

Verified-or-not status lives in `results/probe.json`. Do not invent a new shape without adding it to `scripts/probe_hydradb.py`.

Reads and writes that differ from Neo4j:

- `id` is the node identity. Plain `CREATE` of an edge duplicates the relationship; `MERGE` and `UNWIND … CREATE` do not. Batch dedup key is `(src, dst, type)`.
- The edge-batch form cannot carry labels or properties. A single `MERGE (a:Entity {id: $src})-[:OWNS {source: $source, cost: $cost, rel_id: $rel}]->(b:Entity {id: $dst})` can. `UNWIND … MATCH … SET` is rejected, so cost and label updates are one `MATCH … SET` per edge unless the probe finds a better shape.
- `MERGE` cannot be followed by `SET` in the same statement.
- Batches cap at 1024 items. Chunk at 1000.
- No `RETURN *`, no undirected edges, no unbounded variable length, no `count(DISTINCT …)`, no arithmetic in `RETURN`.
- Path bindings come back only from `CALL algo.* … YIELD path`. `RETURN` may only name yielded columns.
- `maxLen` counts edges. Paths are simple. `pathCount` defaults to 1, which silently returns a single shortest path.
- `relTypes` is the only way to walk several relationship types in one call. Inline that list; composite parameters are rejected inside the procedure map except as an `UNWIND` input. Scalar parameters (`sourceNode`, `maxLen`, `pathCount`, `resultLimit`) are fine.
- `weightProp` is the property shortest-path minimizes. Stamp `cost` on each edge before a weighted call. Omit `weightProp` for the unweighted baseline.
- A `path` cell's `properties` use a capitalised tag (`{"String": "wikidata"}` or `{"Float": 1.0}`), unlike other cells. Relationship ids inside a path are null. Read `src`, `dst`, and `edge_type`.
- Null cells omit `value`. Use `.get("value")`. Node ids come back as `vertex_id`, not `integer`.
- Pagination cursors are consuming iterators. Do not retry a page. DreamGraph path calls ask for a result small enough to fit in one page (`resultLimit` ≤ 8).

Weighted single-source call:

```cypher
CALL algo.SSpaths({
  sourceNode: $src,
  relTypes: ['OWNS_WIKIDATA', 'OWNS_REGISTRY', 'OWNS_SCRAPER'],
  relDirection: 'outgoing',
  maxLen: 2,
  pathCount: $pathCount,
  resultLimit: $resultLimit,
  weightProp: 'cost'
})
YIELD path, pathWeight
RETURN path, pathWeight
```

`$pathCount` and `$resultLimit` are the **same total**. Do not multiply by anything.

Every HTTP body:

```json
{
  "cell_id": "cell-0",
  "query_id": "<new uuid4>",
  "query": "…",
  "parameters": {},
  "consistency": "causal"
}
```

Branch on `error`, then require `rows`. Treat a mutation's empty `rows` as success.

## Learning protocol

Synthetic source noise (fixed, not estimated from the internet):

| Source | P(path ends at the true owner) before drift |
|---|---|
| wikidata | 0.88 |
| registry | 0.72 |
| scraper | 0.30 |

Each relation is a two-hop gadget: company → claim → person, one claim chain per source. There is no cross-link, so a search cannot take a shortcut the generator did not write. Drift swaps **labels only** on `wikidata` and `scraper` edges for `rel_id >= 15`. Endpoints stay put. Held-out relation ids start at 1000, so the whole held-out set drifts. Train ids `0..119` include 15 relations that never drift.

Loop, 1-based iterations, score **then** update:

- At iteration 4, apply drift before scoring.
- Score the 300 held-out questions with the policy currently in force.
- Append a batch of 40 train questions, refit on the last 100 only.
- Guard: fit on `window[:-20]`, test on the last 20. If the new policy's guard accuracy is worse than the current policy, roll back and record a `PolicyVersion` with `rolled_back: true`.
- Greedy updates inside the batch with exponential decay and **no** window and **no** guard.
- Frozen-after-3 takes the same updates as DreamGraph on iterations 1–3 only.
- One-shot updates on iteration 1 only.
- Hand-set costs stay `{wikidata: 1, registry: 2, scraper: 6}`.
- Unweighted search uses weight 1 and the same node-id tie break.
- BM25 ranks the three source paths; the query tokens prefer the literal label `wikidata`.
- The dict learner runs the same refit over `list[dict]` edges and its own Dijkstra.

Chart numbers come only from `results/summary.json` written by `python -m dreamgraph.bench`. No hand-edited metrics.

## Layout

```text
dreamgraph/          library, FastAPI app, benchmark
seed.py              drift entrypoint
scripts/probe_hydradb.py
web/                 React + Vite + Tailwind dashboard
results/             exports of object-store objects
docs/                runbook, loom script, posts
```

Python 3.12. The app is FastAPI on `0.0.0.0:$PORT`. Tests use the in-process graph and a fake Hydra transport. Do not skip a failing test by loosening the assertion; fix the code or document a real engine difference the probe measured.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make test
make bench          # writes the bucket (moto) and exports results/summary.json
make probe          # live engine checks; exit 2 when Docker is absent
make web && make serve
```

`make probe` without Docker still records the registry digest and exits 2. That is not a pass. Cypher is verified only when `results/probe.json` has `"live_engine": true`.
