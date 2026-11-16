# Loom script — about three minutes

Read it while the dashboard is the only thing on screen. The bracketed lines are what you click, not what you say. Numbers are the evidence files, not a rehearsal draft.

## 0:00 — The line

Teams that merge entity data pay when three sources disagree and someone files the wrong person. DreamGraph keeps a cost on each source, refits it when a reviewer says the path was wrong, and asks HydraDB `algo.SSpaths` for the cheapest path. If the new costs lose on a guard slice, the policy rolls back and the receipt stays.

## 0:25 — Four numbers

[Point at the hero.]

Synthetic full path, iteration 8: 90.6 percent, interval 88.4 to 92.4. The 1-hop lookup that spends only the first edge's learned cost, and does not call path search, finishes at 45.9. Book sellers, 30 held-out gold books, three seeds: 96.7 percent, interval 92.2 to 100. Guard rollbacks in the poison run: 15.

## 0:55 — The synthetic chart

[Leave the chart on Synthetic. Point at the drift marker, then the teal line and the dashed 1-hop line.]

Three hundred held-out companies, seeds 0, 1, and 2. The noise is synthetic and labeled. At iteration 4 the wikidata and scraper labels swap. DreamGraph drops to 45.9, then the last-100 window brings it back to 90.6, and every recovered answer is the 3-hop chain. Unweighted stays at 20.7 and never takes that chain. The 1-hop lookup starts ahead, because a node-id tie-break happens to pick the long chain when every cost is 1, and after the swap it stays at 45.9. Summing the path is the part that recovers. The dict learner matches DreamGraph on every iteration. Same sum, outside the engine. I am not going to pretend the engine invented a different objective.

## 1:35 — Book sellers

[Switch the chart to Book sellers.]

This is the public Book data set. Gold author lists from book covers, three real sellers: Revaluation Books, The Book Depository, textbooksNow. On the slice they are right about 96, 63, and 38 percent of the time. The learned costs come out in that order. Accuracy does not move: 96.7 the whole way, same as unweighted, same as 1-hop, same as the dict learner. Alphabetical listing ids already select Revaluation Books, and Revaluation listed every book here. BM25, which does not get that tie-break, sits at 78.9. That is the honest result. The gain is the cost ranking, not a higher accuracy than a lucky tie-break.

## 2:05 — The guard

[Switch the chart to Poison. Scroll the receipts so a rolled-back card is on screen.]

From iteration 4, training reviews call wikidata always wrong and scraper always right. The held-out people do not change. Naive accepts it and drops to 45.9. DreamGraph stays at 90.6. Fifteen receipts, five on each seed. Seed 0, iteration 4: guard accuracy 60 to 40, held-out 91.7 to 44.7, reason "guard accuracy fell". A model frozen after iteration 3 also stays at 90.6, because the poison starts at 4. Hypothesis H9 says that out loud. The receipt is what shows the guard looked.

## 2:35 — One path, live

[Open the live path card. Pick a company marked "modes disagree". DreamGraph, then Unweighted.]

DreamGraph walks the long chain and names the gold person. Unweighted stays on two hops. That answer is `algo.SSpaths` on the running node. The Book tab loads that book's edges into the same node. The latency panel is the benchmark sample, p50 about 6.3 milliseconds, and Measure again hits the live engine.

## 2:55 — Stop

Nine pre-registered hypotheses, all PASS, written by the evaluator from the evidence files. Synthetic gadgets are still gadgets. The book slice is small, and it does not beat its own tie-break. The loom and the posts in `docs/` are drafts. They are not posted.
