# DreamGraph phases

Hard stop: 9:00 AM IST, Monday 16 Nov 2026. Each phase ends in a commit that still boots. Later phases may not start work the cut line names.

The stress-test revisions are already applied in this plan: drift at iteration 4 with a 100-question window and no SHORTCUT or gold-edge pinning; the honest baseline list with 300 held-out questions, 3 seeds, bootstrap intervals, and a drift marker; S3 (moto / Railway bucket), restart-then-write, unique `query_id`, `resultLimit`, app bind 8000, image digest, and `pathCount` as a total cap.

## Phase 0 — Engine contract

**Build**

- `AGENTS.md`, this file.
- `dreamgraph/hydra_client.py`: unique `query_id`, mandatory `cell_id`, `pathCount` and `resultLimit` set to the same total, `weightProp` only on the weighted call, path-cell decoder.
- `dreamgraph/store.py`: S3 JSON put/get. In-process moto when `DG_S3_ENDPOINT` is unset. No durable write to local disk except the explicit export helper.
- `scripts/probe_hydradb.py` and `docs/HYDRA_RUNBOOK.md`.

**Probe (live, only if Docker is available)**

1. Pull `ghcr.io/hydra-db/hydradb:0.4.0` and record index plus `linux/amd64` digests.
2. Start moto, create the bucket, start `graph-node` against that bucket.
3. Run every Cypher shape in the runbook, including weighted `algo.SSpaths`, unweighted `algo.SSpaths`, `algo.SPpaths`, multi-type `relTypes`, and `MATCH … SET` on a relationship property.
4. Measure whether `pathCount` behaves as a total cap. Write the observation; do not "fix" the client to match a hope.
5. Restart the query container against the **same** bucket, read the first write, then write a second node and read both.
6. Confirm two requests carry different `query_id`s.

**If Docker is missing**

- The probe still records the registry digest via HTTPS and writes `results/probe.json` with `"live_engine": false`.
- Exit code 2. The runbook states the exact command to re-run.
- All later phases use `MemoryBackend` and a fake transport in tests. Do not fabricate probe passes or latencies.

**Acceptance**

- `pytest tests/test_client.py tests/test_store.py` passes.
- `results/probe.json` exists and does not claim `live_engine: true` unless every live check passed.
- Client source contains no constant `query_id`.

**Cut line.** Do not block Phase 1 on a live engine. Do not add the dashboard here.

## Phase 1 — World and seed

**Build**

- Synthetic KYC gadgets in `dreamgraph/world.py`. Sources: wikidata 0.88, registry 0.72, scraper 0.30. Two hops, no cross edges, no SHORTCUT generator.
- `apply_drift()` swaps `wikidata` and `scraper` labels for `rel_id >= 15` and is idempotent.
- Train relations `0..119`. Held-out relations `1000..1299` (300).
- `seed.py --drift` prints the swap counts and exits 0.
- Shared Dijkstra in `dreamgraph/search.py` with node-id tie break. Claim ids are shuffled per relation so the unweighted tie is not hard-wired to one source.

**Acceptance**

- Tests prove relations below 15 and `registry` edges are unchanged by drift.
- Tests prove a weighted search follows the cheap source, and after a label swap it follows the other chain.
- No edge cost is written as 0.

**Cut line.** No learner, no chart.

## Phase 2 — Learner, guard, policy versions

**Build**

- Windowed refit on the last `DG_WINDOW` questions (default 100).
- Rollback guard on the last 20 of that window.
- `PolicyVersion` records: iteration, costs, window size, guard accuracy, `rolled_back`.
- Greedy baseline helper: decay 0.85, no window, no guard, so a test can show the two code paths differ.
- Dict refit entry point that accepts `list[dict]`, not `Edge` objects.

**Acceptance**

- A unit test with a hostile guard set rolls back and keeps the previous costs.
- A unit test with 150 logged questions shows the refit input length is 100.
- Costs produced by refit are strictly positive (no gold pinning).

**Cut line.** A rollback that never fires on the full benchmark is acceptable if the unit test fires it and the timeline says zero. Do not inject fake rollback events into `results/`.

## Phase 3 — Evaluation

**Build**

- Methods: `dreamgraph`, `unweighted`, `hand_set`, `one_shot`, `dict_learner`, `greedy`, `bm25`, `frozen_at_3`.
- 8 iterations, drift before the iteration-4 score, score then update, 3 seeds, 300 held-out, stratified bootstrap (1000 resamples, 2.5/97.5).
- Latency sample for the load panel from real `perf_counter` wraps. Report milliseconds even when they are tiny.
- Write the summary through the object store, then export `results/summary.json`.
- Backend field is `memory` unless `DG_BACKEND=hydradb` and the probe's `live_engine` is true. Never silently fall back inside a hydra run.

**Acceptance**

- `results/summary.json` has one series per method, `ci_low` and `ci_high` of length 8, `drift_iter: 4`, `held_out: 300`, `seeds` length 3.
- Re-running the bench is deterministic for the same seeds.
- The README and the UI must not contain a copied accuracy that disagrees with this file. The UI reads the file. The README quotes it and says the noise model is synthetic.

**Cut line.** If recovery is weak, change the learner or the world and re-run. Do not edit the JSON.

## Phase 4 — Dashboard

**Build**

- FastAPI serves the built React app and `/api/health`, `/api/results`, `/api/query`, `/api/load`.
- One dark page: accuracy chart with baseline lines, confidence bands, and a vertical drift marker; query box with an unweighted / DreamGraph toggle and the chosen path; `PolicyVersion` timeline including rollbacks; load panel with p50 / p95 / p99.
- Visual language in the spirit of a clean operations console (cards, one accent, a crisp line chart, a segmented toggle). Hand-built components. No copied proprietary markup.
- Empty state when `results/summary.json` is absent. Error state when `/api/results` fails. Loading state while the first fetch is in flight.
- Query answers are computed on request from the regenerated world and the saved policy, not looked up from a hard-coded path table.
- Bind `0.0.0.0` and port `PORT` (default 8000).

**Acceptance**

- `GET /api/health` returns 200 on the bound port.
- The chart's series names match the JSON keys.
- Toggling mode changes the request. At least one demo question differs between modes after drift; the bench records those relation ids.
- Desktop and a narrow layout both stack without a clipped control.

**Cut line.** No authentication, no accounts, no extra product surface.

## Phase 5 — Package and the story

**Build**

- `Dockerfile` for the app (builds the web assets, binds `$PORT`).
- `docker-compose.yml` for moto + HydraDB `0.4.0` + the app.
- `railway.toml` for the app and `deploy/hydradb.railway.toml` plus env example for the engine and a Railway bucket.
- `Makefile` targets: `install`, `test`, `bench`, `probe`, `web`, `serve`.
- `README.md`: problem, buyer (teams merging multi-vendor entity data, KYC or B2B enrichment), architecture diagram, results table taken from the JSON, how to reproduce, limitations, synthetic-noise label, precomputed-export label.
- `docs/LOOM_SCRIPT.md`: a three-minute walkthrough.
- `docs/POSTS.md`: two X drafts that tag `@hydra_db`.

**Acceptance**

- `make test` passes.
- `make bench` rewrites `results/summary.json` with the same accuracies.
- The app serves the dashboard.
- Nothing is deployed, posted, or published.

**Cut line.** Stop. Leave Railway clicks, a live Hydra probe, and the loom recording to the human if they are not already done.
