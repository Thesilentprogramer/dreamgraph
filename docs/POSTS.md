# Drafts for X

Not posted. Both tag `@hydra_db`. The accuracies are the evidence files: synthetic HydraDB series in `results/summary.json`, 1-hop replay in `results/one_hop.json`, Book slice in `results/public_summary.json`, poison receipts in `results/poison.json`.

## 1

Track 1: the cost on the edge is what `algo.SSpaths` minimizes, and a bad refit has to be able to lose.

DreamGraph learns a cost per source from reviewer feedback. On the synthetic ownership graph the true owner is a 3-hop chain. After the wikidata/scraper label swap, held-out accuracy (300 questions, 3 seeds) falls from 90.6% to 45.9%, then the last-100 window brings it back to 90.6% (95% CI 88.4–92.4). Every recovered answer is the 3-hop path. A 1-hop lookup that spends only the first edge's learned cost stays at 45.9%. Unweighted search stays at 20.7% and its 3-hop rate stays 0.

The same loop on a public Book slice (Revaluation Books, The Book Depository, textbooksNow; 30 held-out gold books) finishes at 96.7% (CI 92.2–100). It ties unweighted, because the tie-break already picks the best seller. The learned costs still rank them 0.041, 0.839, 1.545. @hydra_db

## 2

Honest ablation: the dict learner matches DreamGraph on every synthetic iteration and every Book iteration. Same path-cost sum, outside the engine. HydraDB is the search that consumes the cost.

The guard is the part that is not a tie. From iteration 4 a poisoned review stream calls wikidata always wrong. Naive accuracy falls to 45.9%. DreamGraph rolls the update back 15 times (5 per seed) and stays at 90.6%. One receipt: guard 60% → 40%, held-out 91.7% → 44.7%. A model frozen before the poison also survives. The hypotheses say so, including that one. Nine checks, nine PASS, generated from the evidence files. @hydra_db
