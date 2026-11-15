# Drafts for X

Not posted. Both tag `@hydra_db`. The accuracies below are the live `algo.SSpaths` run in `results/summary.json`.

## 1

Track 1: when the labels flip, the path has to be recomputed, not just relabeled.

DreamGraph stores a learned cost on each ownership edge and asks HydraDB `algo.SSpaths` for the minimum sum. Three hops that are usually the true owner compete with two shorter chains. At iteration 4 we swap the Wikidata and scraper labels. Held-out accuracy (300 questions, 3 seeds) falls from 90.6% to 45.9%, then the last-100 window brings it back to 90.6% (95% CI 88.4–92.4). Every recovered answer is the 3-hop path. Unweighted search stays at 20.7% and never takes it.

Synthetic chain noise. 20 concurrent clients, p50 6.3 ms on the path call. @hydra_db

## 2

Honest ablation from the same DreamGraph run: the identical sum on plain Python dicts matched HydraDB's accuracies on all 8 iterations. The engine is doing the walk. The learning rule is not hiding inside it.

What the dict walk does not change: unweighted `algo.SSpaths` has a 3-hop rate of 0. Greedy, with no window, ends at 61.6% and only a third of its answers are the long chain. Hand-set costs stay at 45.9% after the swap. The chart is the path composition, not a second copy of the update rule. @hydra_db
