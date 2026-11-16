import { useEffect, useState } from "react";
import Chart from "./Chart.jsx";

const GITHUB = "https://github.com/Thesilentprogramer/dreamgraph";

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

export default function Landing() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/results")
      .then(async (response) => {
        if (!response.ok) throw new Error("Results are not ready");
        return response.json();
      })
      .then((body) => {
        if (!cancelled) setResults(body);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Results are not ready");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const vuln = results?.vuln;
  const poison = results?.vuln_poison;
  const dream = vuln?.series?.dreamgraph?.accuracy?.at(-1);
  const nvd = vuln?.series?.nvd_only?.accuracy?.at(-1);
  const guarded = poison?.series?.dreamgraph?.accuracy?.at(-1);
  const naive = poison?.series?.naive?.accuracy?.at(-1);
  const held = vuln?.config?.held_out;
  const hidden = {
    bm25: true,
    ghsa_only: true,
    one_shot: true,
    greedy: true,
    one_hop: true,
    hand_set: true,
    unweighted: true,
    dict_learner: true,
    frozen_at_3: true,
    naive: true,
    topk_open: true,
    conditional_k1: true,
    per_feed: true,
    majority: true,
  };

  return (
    <div className="frame landing">
      <header className="wrap" style={{ paddingTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center" }}>
          <p className="meta">DreamGraph</p>
          <nav style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <a className="sq sq-invert" href="/dashboard">See the live dashboard</a>
            <a className="sq" href={GITHUB}>Get the GitHub repo</a>
          </nav>
        </div>
      </header>

      <section className="hero wrap" data-enter>
        <p className="meta">HydraDB track 1</p>
        <h1 className="display" style={{ margin: "16px 0 0" }}>
          Feed-trust graph for security teams
        </h1>
        <p style={{ maxWidth: 620, marginTop: 20 }}>
          DreamGraph learns which vulnerability feed to believe, then HydraDB’s weighted path search spends that cost on the verdict.
        </p>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 28, alignItems: "stretch" }}>
          <div className="nb" style={{ padding: "16px 18px", minWidth: 180 }}>
            <p className="stat">{pct(dream)}</p>
            <p className="meta" style={{ marginTop: 8 }}>DreamGraph held out</p>
          </div>
          <div className="nb" style={{ padding: "16px 18px", minWidth: 180, background: "#d6ff4a" }}>
            <p className="stat">{pct(nvd)}</p>
            <p className="meta" style={{ marginTop: 8 }}>NVD only</p>
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 28 }}>
          <a className="sq sq-invert" href="/dashboard">See the live dashboard</a>
          <a className="sq" href="/graph">Open the 3D graph</a>
          <a className="sq" href={GITHUB}>Get the GitHub repo</a>
        </div>
        {error && <p className="meta" style={{ marginTop: 16 }}>{error}</p>}
      </section>

      <section className="band-lime">
        <div className="wrap">
          <h2>Feeds that disagree</h2>
          <p style={{ maxWidth: 640, marginTop: 16 }}>
            NVD, Debian, SUSE, Rocky and the rest publish different ranges for the same tag. A single global trust score hides the project where Linux is perfect and Rocky is wrong.
          </p>
          <div className="steps" style={{ marginTop: 32 }}>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">NVD</p>
              <p style={{ marginTop: 8 }}>Broad coverage. Right often, wrong on the distro that already patched.</p>
            </article>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">Distro feeds</p>
              <p style={{ marginTop: 8 }}>Narrow and sharp. Linux is exact on its own packages and silent everywhere else.</p>
            </article>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">A bad mirror</p>
              <p style={{ marginTop: 8 }}>An aggregator that flips NVD looks like a new source until the guard throws the update out.</p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <h2>Three steps in the loop</h2>
          <div className="steps" style={{ marginTop: 28 }}>
            <article className="nb" style={{ padding: 18 }}>
              <p className="step-no">1</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Claims in HydraDB</h3>
              <p style={{ marginTop: 8 }}>Each feed is a two-edge chain from the question to affected or not.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <p className="step-no">2</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Weighted path search</h3>
              <p style={{ marginTop: 8 }}>algo.SPpaths returns the cheapest verdict paths. A near tie shares the vote.</p>
            </article>
            <article className="nb" style={{ padding: 18, background: "#070ef4", color: "#f4f5fa" }}>
              <p className="step-no">3</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Guard rolls back</h3>
              <p style={{ marginTop: 8 }}>A proposal that gets worse on the guard slice, or on reviews already logged, is refused.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="band-blue">
        <div className="wrap">
          <h2>Live held-out numbers</h2>
          <p className="meta" style={{ marginTop: 12 }}>{held ? `${held.toLocaleString("en-US")} tags · 3 seeds` : "Loading the export"}</p>
          <div className="steps" style={{ marginTop: 28 }}>
            {[
              ["DreamGraph", pct(dream)],
              ["NVD only", pct(nvd)],
              ["Majority", pct(vuln?.series?.majority?.accuracy?.at(-1))],
              ["Per-feed cost", pct(vuln?.series?.per_feed?.accuracy?.at(-1))],
            ].map(([label, value]) => (
              <article key={label} className="nb" style={{ padding: 16, background: "#f3ede2", color: "#111" }}>
                <p className="stat">{value}</p>
                <p className="meta" style={{ marginTop: 8 }}>{label}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <h2>Accuracy by iteration</h2>
          <p style={{ maxWidth: 640, marginTop: 12 }}>
            Solid line is DreamGraph. Dashed line is NVD only. The block is the newer half of the feeds.
          </p>
          <div className="nb-flat" style={{ marginTop: 24, padding: 12 }}>
            {vuln?.series ? (
              <Chart
                series={vuln.series}
                markers={[{ iter: vuln.drift_iter || 4, label: "NEWER FEEDS" }]}
                hidden={hidden}
                onToggle={() => {}}
              />
            ) : (
              <p className="meta">Waiting for /api/results</p>
            )}
          </div>
          <p style={{ marginTop: 16 }}>
            <a className="sq" href="/dashboard">Compare every baseline</a>
          </p>
        </div>
      </section>

      <section className="band-lime">
        <div className="wrap">
          <h2>Poison guard</h2>
          <p style={{ maxWidth: 640, marginTop: 16 }}>
            From iteration 4, new reviews call NVD wrong and a mirror right. Older reviews stay as written.
          </p>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 28 }}>
            <article className="nb" style={{ padding: 18, background: "#f3ede2", minWidth: 200 }}>
              <p className="stat">{pct(guarded)}</p>
              <p className="meta" style={{ marginTop: 8 }}>DreamGraph with the guard</p>
            </article>
            <article className="nb" style={{ padding: 18, background: "#111", color: "#f4f5fa", minWidth: 200 }}>
              <p className="stat">{pct(naive)}</p>
              <p className="meta" style={{ marginTop: 8 }}>Naive, no guard</p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <h2>Who pays for this</h2>
          <div className="steps" style={{ marginTop: 28 }}>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>SCA feed-trust API</h3>
              <p style={{ marginTop: 8 }}>A platform team asks which feed to trust for this project, and gets a path cost instead of a tie.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>Weekly leaderboard</h3>
              <p style={{ marginTop: 8 }}>Publish the learned costs and the held-out score every week, from the same export the dashboard reads.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>Free GitHub Action</h3>
              <p style={{ marginTop: 8 }}>The distribution step: a pull request comment that names the feed the path search trusted.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="band-blue">
        <div className="wrap">
          <h2>Built on HydraDB</h2>
          <p style={{ maxWidth: 640, marginTop: 16 }}>
            The graph lives in HydraDB OSS. DreamGraph writes a cost on each claim edge and reads the verdict paths back from algo.SPpaths. The learner does not pin a gold edge to zero.
          </p>
          <p style={{ marginTop: 20 }}>
            <a className="sq" href="/graph" style={{ background: "#d6ff4a" }}>Open the 3D graph</a>
          </p>
        </div>
      </section>

      <footer className="wrap" style={{ paddingBottom: 28 }}>
        <hr className="rule" />
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
          <p className="meta">Source: Zenodo 16440960 · OSV · NVD</p>
          <p className="meta">© DreamGraph</p>
        </div>
      </footer>
    </div>
  );
}
