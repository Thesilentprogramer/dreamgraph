# Drafts for X

Not posted. Both tag `@hydra_db`. Numbers are the evidence files, including the FAIL.

## 1

When NVD, GitHub, and distro feeds disagree on what is actually vulnerable, DreamGraph learns which source to trust, and HydraDB's weighted path search uses those costs.

Gold is Zenodo 16440960 (CC BY 4.0): manual affected tags, not a feed grading itself. On 1,317 held-out tags and 3 seeds, DreamGraph finishes at 65.0% (95% CI 63.5–66.5). Majority vote is 59.5%. NVD alone is 64.9%. The intervals overlap. Learned cost still tracks error: Linux 0.039 / 100% (n=74), NVD 0.35 / 66%, Rocky 2.06 / 46%, a bad NVD mirror 2.95 / 34%. Spearman 0.96.

GitHub's advisory API returned these CVEs with no version ranges, so the GHSA baseline abstains (50.8%). Drift is real: newer `modified` times, NVD +10 points, SUSE −10. @hydra_db

## 2

The guard is not magic. From iteration 4, reviews call NVD wrong and a mirror that flips NVD's range right. Eleven rollbacks. Naive accuracy falls to 35.1%. DreamGraph's mean falls to 54.7% because seed 2 accepted the poisoned update. A model frozen after iteration 3 stays at 65.1%. That hypothesis is FAIL, and it is printed that way.

On the synthetic ownership graph the same learner still does the thing path search is for: full sum 90.6% (CI 88.4–92.4) against a 1-hop lookup at 45.9%, and the dict learner matches because it computes the same sum outside the engine. @hydra_db
