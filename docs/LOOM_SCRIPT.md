# Loom script — about three minutes

Read while showing the landing page and dashboard. Bracketed lines are clicks. Numbers come from committed evidence exports.

## 0:00 — Scanner noise

[Show the landing hero.]

Your scanner says vulnerable. Your distro says patched. Who is right? Dependabot, Snyk, Trivy, and Grype can flag a package version using NVD while a distro says the fix is already shipped or that version was never affected. Every contradiction costs triage time. Enough false alarms and teams risk missing a real one.

## 0:30 — The trust path

[Scroll to the steps and the example card.]

DreamGraph learns which feed is right for each project from reviewed outcomes. Each feed claim gets a positive edge cost in HydraDB. Weighted path search returns a verdict and the route behind it. The ImageMagick 7.0.11-1 / CVE-2023-3745 card is an honest miss: NVD says affected, three distro feeds say not affected, the saved policy follows NVD at cost 1.064, and the gold label is not affected. We can audit exactly why the model was wrong.

## 1:10 — Proof

[Point at the held-out numbers and chart.]

The real-data slice uses OSV feeds against hand-labeled Zenodo 16440960 gold, covering 1,128 CVEs. Across 1,317 held-out checks and three seeds, DreamGraph rises from 57.1 to 68.2 percent, with a 95 percent interval of 66.8 to 69.6. NVD alone is 64.9; majority vote is 59.5. The marker is the newer-feed time cut, not a simulated label swap. The dict learner matches the accuracy; HydraDB supplies the weighted path search.

## 1:50 — Can't be fooled by a bad feed

[Switch to Poison. Show a rolled-back receipt.]

From iteration 4, poisoned reviews falsely call NVD wrong and a modeled mirror right. The guard checks proposed costs against earlier reviews and refuses a worse update. The naive learner collapses to 35.0 percent. DreamGraph holds 65.1, tied with the model frozen after iteration 3. Thirteen updates roll back across all three seeds.

## 2:25 — Who uses it

[Return to the landing page's final sections.]

SCA vendors and platform/security teams could consume a feed-trust API that names the verdict, the source paths, and the costs. A weekly public leaderboard could show trust by project. A free GitHub Action could annotate scanner alerts. Those are proposed distribution paths, not shipped integrations.

## 2:50 — Close

[Open the dashboard or graph.]

The live query shows the path search on the running HydraDB node. The synthetic ownership experiment, its ablations, the full baselines, and all 16 pre-registered checks remain in the repo. The loom and posts are drafts, not published.
