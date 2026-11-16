# Drafts for X

Not posted. Both tag `@hydra_db`. Numbers come from the committed evidence exports.

## 1 — The scanner-noise problem

Your scanner says vulnerable. Your distro says patched. Who is right? Dependabot, Snyk, Trivy, and Grype can surface an NVD alert while Debian, Red Hat, SUSE, or Alpine says the package version is fixed or never affected. Teams spend hours triaging contradictions; eventually the noise can hide a real alert.

DreamGraph learns feed trust per project from reviews, writes that trust as positive edge costs in HydraDB, and returns an auditable path to “affected” or “not affected.” On real OSV feeds against hand-labeled Zenodo 16440960 gold (1,128 CVEs), it rises from 57.1% to 68.2% (95% CI 66.8–69.6) across 1,317 held-out checks and 3 seeds. NVD alone: 64.9%. Majority vote: 59.5%. The dict learner matches DreamGraph's accuracy; HydraDB runs the weighted path search. @hydra_db

## 2 — The bad-feed guard

What if a mirror is wrong or review feedback is poisoned? In the NVD-mirror test, new reviews falsely call NVD wrong and the mirror right. DreamGraph checks each proposed update against earlier reviews and rolls it back when accuracy falls. The naive learner ends at 35.0%; DreamGraph holds 65.1%, tied with a model frozen after iteration 3. There are 13 rollbacks across all 3 seeds. The mirror is modeled, not a downloaded feed.

The product path: a feed-trust API for SCA vendors and security teams, a weekly public feed-trust leaderboard, and a free GitHub Action that annotates scanner alerts with a verdict and its trust path. These are proposed channels, not shipped integrations. @hydra_db
