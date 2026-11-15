# Drafts for X

Not posted. Both tag `@hydra_db`. Do not publish the accuracy lines as a HydraDB measurement until `results/probe.json` says `"live_engine": true` and the bench has been re-run against the engine. Until then, keep the "in-process" clause.

## 1

Track 1: the graph should get sharper when a vendor flips.

DreamGraph refits the cost of Wikidata, a registry, and a scraper from reviewer feedback, then walks the cheap path. At iteration 4 we swap the Wikidata and scraper labels. Held-out accuracy (300 questions, 3 seeds) falls from 85.0% to 47.0%, then the last-100 window brings it back to 80.4% (95% CI 77.7–82.9). Hand-set costs stay at 33.8%. Unweighted never moves: 63.0% the whole way.

Synthetic source noise. Path search is the `algo.SSpaths` shape; this run's numbers are the in-process graph, probe not yet live. @hydra_db

## 2

Honest baseline from the same DreamGraph run: the identical learner on plain Python dicts matched the graph line on all 8 iterations. HydraDB is there to run the weighted path search, not to hide the update rule.

A model frozen after iteration 3 stays at 47.0% after the label swap. Seed 2 rolled the new costs back twice because a 20-question guard got worse. Greedy, with no window, still recovered. The chart is only as good as the baseline you refuse to drop. @hydra_db
