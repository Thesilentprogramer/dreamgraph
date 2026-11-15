# Loom script — about three minutes

Read it while the dashboard at `http://127.0.0.1:8000` is the only thing on screen. Do not publish this take until a live HydraDB probe has passed, or say the caveat out loud. The bracketed lines are what you click, not what you say.

## 0:00 — The bill

Teams that merge KYC or B2B entity data pay when three vendors disagree about who owns a company, and someone files the wrong person. DreamGraph is the graph that keeps a cost on each vendor and changes that cost when reviewers say the path was wrong. It is a HydraDB Track 1 entry: the links are supposed to get sharper every run.

## 0:25 — The picture

[Point at the four numbers, then the chart.]

This page is one precomputed run. Three hundred held-out companies, three seeds. The noise is synthetic and labeled: before anything breaks, a Wikidata chain is right about eighty-eight percent of the time, the registry about seventy-two, the scraper about thirty. The lines are not mocked. They come from `results/summary.json`.

DreamGraph starts even with an unweighted walk, at sixty-three percent, because it has not seen a review yet. One update later it is at eighty-five, in line with the hand-set costs.

## 1:05 — The swap

[Point at the dashed marker on iteration 4.]

At iteration four we swap the Wikidata and scraper labels on every relation from fifteen up. We do not move the people. We only change the name on the edge. The score on that iteration still uses the old costs, so DreamGraph drops to forty-seven percent. The ninety-five percent interval there is forty-four to fifty. Hand-set costs, BM25, and a one-shot fit fall to thirty-three point eight and never come back, because they still believe the word Wikidata. A copy frozen after iteration three stays at forty-seven.

[Trace the teal line back up.]

The learner refits on only the last hundred reviews. By iteration six DreamGraph is at eighty point four, interval seventy-seven point seven to eighty-two point nine. The unweighted line never moves. It is sixty-three the whole way, because the tie break is node ids, and the swap did not change those.

## 1:50 — Say the honest part

[Hover the dict-learner legend.]

The dashed twin is the same learner on plain Python dicts. It matches DreamGraph on every iteration. I am not going to pretend otherwise. HydraDB's job in this design is the weighted path search, `algo.SSpaths`, not a secret update rule. On this machine Docker was not available, so that search ran in-process. The probe file says `live_engine: false`. The microseconds in the latency panel are not a database round trip.

## 2:15 — One company

[Open the query card. Pick a company marked "modes disagree". Leave it on DreamGraph, then press Unweighted.]

DreamGraph walks the scraper chain and names the true owner. Unweighted still walks the edges that are labeled Wikidata, and names the decoy. That answer is computed when you click, from the saved costs and the regenerated graph. It is not a row someone pasted into the page.

## 2:35 — The guard

[Scroll the policy list so a red "Rolled back" card is on screen. Seed 2, iterations 4 and 5.]

Two refits were rejected. The guard holds out the last twenty questions in the window, and if the new costs do worse there, the previous costs stay. Seed two hit that at the swap and on the next iteration. The other seeds accepted every update. Greedy, with no window and no guard, also climbs back, so the window is not magic. The rollback is the part you can see.

## 2:55 — Stop

Synthetic gadgets, no shared ownership graph, no live engine call in the published numbers. The runbook is `docs/HYDRA_RUNBOOK.md` if you want the probe on `ghcr.io/hydra-db/hydradb:0.4.0` before you send this anywhere.
