# Loom script — about three minutes

Read it while the dashboard is the only thing on screen. The bracketed lines are what you click. Numbers are the evidence files.

## 0:00 — The line

When NVD, GitHub, and the distro feeds disagree on what is actually vulnerable, DreamGraph learns which source to trust, and HydraDB's weighted path search uses those costs to answer. The gold is a manual Zenodo set of affected upstream tags, not a feed grading itself. GitHub's advisory API had no version ranges for these CVEs, so that baseline abstains.

## 0:25 — Four numbers

[Point at the hero.]

Synthetic full path, iteration 8: 90.6 percent, interval 88.4 to 92.4. The 1-hop lookup finishes at 45.9. Vulnerability feeds, 1,317 held-out tags, three seeds: DreamGraph 65.0 percent, interval 63.5 to 66.5. NVD-mirror rollbacks: 11. Say the next sentence: seed 2 accepted the poisoned update.

## 0:55 — The feeds

[Switch the chart to Vuln feeds. Point at the source table.]

Majority vote, which lets the noisy distros outvote NVD, is 59.5. NVD alone is 64.9. DreamGraph is 65.0. The intervals overlap NVD and the unweighted walk. What does not overlap is the cost table. Linux, on 74 judgments, is cost 0.039 and accuracy 100. NVD is 0.35 and 66 percent. Rocky is 2.06 and 46 percent. The modeled mirror that flips NVD is 2.95 and 34 percent. Spearman of cost against error is 0.96. Drift is real: newer records make NVD 10 points more accurate and SUSE 10 points worse. The marker is that time cut, not a label swap I invented.

## 1:40 — The guard, including the miss

[Switch to Poison. Scroll a rolled-back receipt, then say the seed that is missing.]

From iteration 4 the reviews call NVD wrong and the bad mirror right. Eleven receipts. Seed 0, iteration 4: guard 60 to 45, held-out 65 to 36. Naive ends at 35.1. DreamGraph's mean falls to 54.7 because seed 2 never rolled back. The model frozen after iteration 3 stays at 65.1. Hypothesis H12 is FAIL. I am not going to hide that. The guard fired where the validation slice dropped. It did not fire on every seed.

## 2:20 — One tag, live

[Open the live path. Pick a package tag. Leave it on DreamGraph.]

The path is question, claim, verdict. That is `algo.SSpaths` on the running node, with the learned costs stamped on the edges. Unweighted is the same graph with every edge weight 1.

## 2:45 — Stop

Twelve pre-registered checks. Eleven PASS, H12 FAIL. The synthetic ownership chart is still there, and on that one the dict learner matches and the 3-hop rate is the whole result. The loom and the posts are drafts. They are not posted.
