# Drafts for X

Not posted. Both tag `@hydra_db`. Numbers are the evidence files, including the FAIL.

## 1

When NVD, GitHub, and distro feeds disagree on what is actually vulnerable, DreamGraph learns which source to trust, and HydraDB's weighted path search uses those costs.

Gold is Zenodo 16440960 (CC BY 4.0): manual affected tags, not a feed grading itself. On 1,317 held-out tags and 3 seeds, DreamGraph finishes at 68.2% (95% CI 66.8–69.6). NVD alone is 64.9% (63.5–66.4). Those intervals do not overlap. Majority vote is 59.5%. A single cost per feed finishes at 63.3%, below NVD. Learned cost still tracks error: Linux 0.082 / 100% (n=74), NVD 0.48 / 66%, Rocky 1.67 / 46%, a bad NVD mirror 2.20 / 34%. Spearman 0.96.

GitHub's advisory API returned these CVEs with no version ranges, so the GHSA baseline abstains (50.8%). Drift is real: newer `modified` times, NVD +10 points, SUSE −10. @hydra_db

## 2

The guard keeps reviews as they were logged. From iteration 4, new reviews call NVD wrong and a mirror that flips NVD's range right. Thirteen rollbacks, including four on seed 2. Naive accuracy falls to 35.0%. DreamGraph stays at 65.1%, tied with the model frozen after iteration 3. H12 is PASS. The threshold did not move.

On the synthetic ownership graph the same learner still does the thing path search is for: full sum 90.6% (CI 88.4–92.4) against a 1-hop lookup at 45.9%, and the dict learner matches because it computes the same sum outside the engine. @hydra_db
