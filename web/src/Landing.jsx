import { useState } from "react";
import Chart from "./Chart.jsx";
import { navigate } from "./route.js";
import useResults from "./useResults.js";

const GITHUB = "https://github.com/Thesilentprogramer/dreamgraph";
const EXAMPLE = { cve: "CVE-2022-4304", package: "openssl", version: "OpenSSL_1_1_1t" };

function TryIt() {
  const [fields, setFields] = useState(EXAMPLE);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function check(event) {
    event.preventDefault();
    setLoading(true);
    setResult(null);
    setError("");
    try {
      const response = await fetch("/api/verdict", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(response.status === 404 ? "This tag is outside the Zenodo graph. Try the prefilled example." : typeof body.detail === "string" ? body.detail : "The graph could not answer yet. Try again shortly.");
      setResult(body);
    } catch (caught) {
      setError(caught.message || "The graph could not answer yet. Try again shortly.");
    } finally {
      setLoading(false);
    }
  }

  const curl = [
    "curl -G 'https://dreamgraph.onrender.com/api/verdict' \\",
    `  --data-urlencode 'cve=${EXAMPLE.cve}' \\`,
    `  --data-urlencode 'package=${EXAMPLE.package}' \\`,
    `  --data-urlencode 'version=${EXAMPLE.version}'`,
  ].join("\n");
  const claude = JSON.stringify({ mcpServers: { dreamgraph: { type: "http", url: "https://dreamgraph.onrender.com/mcp" } } }, null, 2);
  const cursor = JSON.stringify({ mcpServers: { dreamgraph: { url: "https://dreamgraph.onrender.com/mcp" } } }, null, 2);

  return <section id="try-it" className="band-blue try-it"><div className="wrap">
    <h2>Try a verdict</h2>
    <p>Check a tag from the Zenodo set. DreamGraph uses HydraDB when ready and replays the same weighted vote while it warms up.</p>
    <form onSubmit={check} className="try-form">
      {[["cve", "CVE"], ["package", "Package"], ["version", "Version"]].map(([key, label]) => <label key={key}>{label}<input name={key} value={fields[key]} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} required maxLength={128} /></label>)}
      <button className="sq" type="submit" disabled={loading}>{loading ? "Checking…" : "Check vulnerability"}</button>
    </form>
    {error && <p className="try-error" role="alert">{error}</p>}
    {result && <div className="try-result nb" role="status">
      <div><p className="meta">Policy version {result.policy_version} · {result.engine === "hydradb-live" ? "HydraDB live" : "Offline replay"}</p><h3 className="display">{result.verdict.replaceAll("_", " ")}</h3><p>Vote share: {pct(result.confidence)} · Gold label: {result.gold_label?.replaceAll("_", " ")}</p>{result.note && <p className="try-note">{result.note}</p>}</div>
      <div><h4>Trust paths</h4><ul>{result.trust_paths.map((path, index) => <li key={`${path.feed}-${index}`}><strong>{path.feed}</strong> → {path.claim.replaceAll("_", " ")} <span>feed cost {path.trust_cost?.toFixed(3)} · path cost {path.path_cost.toFixed(3)}{path.in_vote ? " · in vote" : ""}</span></li>)}</ul></div>
      <p className="try-note">Confidence is a share of weighted path votes, not a calibrated probability.</p>
    </div>}
    <div className="try-snippets"><div><h3>Curl</h3><pre>{curl}</pre></div><div><h3>Claude Code · .mcp.json</h3><pre>{claude}</pre><h3>Cursor · .cursor/mcp.json</h3><pre>{cursor}</pre></div></div>
  </div></section>;
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function MiniCurve({ series, driftIter, error }) {
  const learned = series?.dreamgraph?.accuracy;
  const baseline = series?.nvd_only?.accuracy;
  const width = 420;
  const height = 240;
  const x = (index) => 24 + (index / (learned.length - 1)) * 368;
  const y = (value) => 204 - ((value - 0.45) / 0.30) * 160;
  const points = (values) => values.map((value, index) => `${x(index)},${y(value)}`).join(" ");

  return (
    <div className="hero-curve nb">
      <div className="hero-curve-head">
        <p className="meta">Held-out accuracy</p>
        <p className="meta">8 iterations · 3 seeds</p>
      </div>
      {learned && baseline ? (
        <>
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`DreamGraph accuracy ends at ${pct(learned.at(-1))}; NVD ends at ${pct(baseline.at(-1))}`}>
            {[0.5, 0.6, 0.7].map((tick) => (
              <g key={tick}>
                <line x1="24" x2="392" y1={y(tick)} y2={y(tick)} stroke="white" opacity="0.25" />
                <text x="392" y={y(tick) - 6} textAnchor="end" fill="white" opacity="0.75" fontSize="11">{Math.round(tick * 100)}%</text>
              </g>
            ))}
            <rect x={x((driftIter || 4) - 1) - 9} y="28" width="18" height="176" fill="#d6ff4a" opacity="0.2" />
            <polyline points={points(baseline)} fill="none" stroke="white" strokeWidth="2" strokeDasharray="7 6" />
            <polyline points={points(learned)} fill="none" stroke="#d6ff4a" strokeWidth="4" strokeLinejoin="round" />
            {learned.map((value, index) => <rect key={index} x={x(index) - 4} y={y(value) - 4} width="8" height="8" fill="#d6ff4a" />)}
          </svg>
          <div className="hero-curve-legend"><span><i className="legend-learned" /> DreamGraph {pct(learned.at(-1))}</span><span><i className="legend-nvd" /> NVD {pct(baseline.at(-1))}</span></div>
          <p className="meta">DreamGraph 95% CI {pct(series.dreamgraph.ci_low?.at(-1))}–{pct(series.dreamgraph.ci_high?.at(-1))}</p>
          <p className="meta">Newer feeds enter at iteration {driftIter || 4}</p>
        </>
      ) : (
        <div className="hero-curve-wait" role="status">{error ? `Results unavailable: ${error}` : "Waking the graph engine. Waiting for /api/results…"}</div>
      )}
    </div>
  );
}

export default function Landing() {
  const { results, error } = useResults();

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
        <div className="hero-copy">
        <p className="meta">HydraDB track 1</p>
        <h1 className="display" style={{ margin: "16px 0 0" }}>
          Your scanner says vulnerable. Your distro says patched. Who’s right?
        </h1>
        <p style={{ maxWidth: 620, marginTop: 20 }}>
          Dependabot, Snyk, Trivy, and Grype can flag a version from NVD while its distro feed says the fix is already shipped or the package was never affected. DreamGraph learns which feed to trust for each project and shows the path behind every verdict.
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
          <a className="sq" href="/graph" onClick={(event) => { event.preventDefault(); navigate("/graph"); }}>Open the 3D graph</a>
          <a className="sq" href={GITHUB}>Get the GitHub repo</a>
        </div>
        {error && <p className="meta" style={{ marginTop: 16 }}>{error}</p>}
        </div>
        <MiniCurve series={vuln?.series} driftIter={vuln?.drift_iter} error={error} />
      </section>

      <TryIt />

      <section className="band-lime">
        <div className="wrap">
          <h2>Scanner noise eats the triage day</h2>
          <p style={{ maxWidth: 640, marginTop: 16 }}>
            The same package version can trigger an alert in one scanner and a patched or not-affected verdict in its distro feed. Security teams spend hours reconciling feeds. When every alert looks suspect, real vulnerabilities are easier to miss.
          </p>
          <div className="steps" style={{ marginTop: 32 }}>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">NVD</p>
              <p style={{ marginTop: 8 }}>Broad coverage can flag a package even when the distro has backported the fix.</p>
            </article>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">Distro feeds</p>
              <p style={{ marginTop: 8 }}>Debian, Red Hat, SUSE, and Alpine know their packages, but coverage and accuracy vary by project.</p>
            </article>
            <article className="nb" style={{ padding: 16, background: "#f3ede2" }}>
              <p className="meta">A bad mirror</p>
              <p style={{ marginTop: 8 }}>A wrong or poisoned mirror can add more noise; its claimed authority needs to be tested.</p>
            </article>
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <h2>From conflicting alerts to a trust path</h2>
          <div className="steps" style={{ marginTop: 28 }}>
            <article className="nb" style={{ padding: 18 }}>
              <p className="step-no">1</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Claims in HydraDB</h3>
              <p style={{ marginTop: 8 }}>Each feed makes a claim about a project, version, and CVE. The graph keeps the source attached to the claim.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <p className="step-no">2</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Weighted path search</h3>
              <p style={{ marginTop: 8 }}>Reviews set positive costs for each feed and project. HydraDB returns the lowest-cost paths to affected or not affected, including the feeds behind them.</p>
            </article>
            <article className="nb" style={{ padding: 18, background: "#070ef4", color: "#f4f5fa" }}>
              <p className="step-no">3</p>
              <h3 className="display" style={{ fontSize: 28, marginTop: 12 }}>Guard rolls back</h3>
              <p style={{ marginTop: 8 }}>If a refit performs worse on held-back reviews, the prior policy stays in force.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="band-lime">
        <div className="wrap">
          <h2>One disagreement, with the receipts</h2>
          <p style={{ maxWidth: 700, marginTop: 16 }}>ImageMagick 7.0.11-1 · CVE-2023-3745 is a real case in the explorer export. NVD says affected; Debian, openSUSE, and SUSE say not affected.</p>
          <article className="nb" style={{ padding: 20, marginTop: 24, maxWidth: 760, background: "#f3ede2" }}>
            <p className="meta">Saved policy · ImageMagick · CVE-2023-3745</p>
            <h3 className="display" style={{ fontSize: 32, marginTop: 14 }}>Verdict: affected</h3>
            <p style={{ marginTop: 12 }}>Trust path: question → NVD claim → affected. Total path cost: 1.064. The alternative openSUSE path to not affected costs 1.352; SUSE costs 1.535 and Debian 2.363.</p>
            <p style={{ marginTop: 12 }}><strong>Gold label: not affected.</strong> This example is a miss. The path makes the wrong call inspectable so a reviewer can correct the trust policy.</p>
            <p style={{ marginTop: 16 }}><a className="sq" href="/graph" onClick={(event) => { event.preventDefault(); navigate("/graph"); }}>Inspect the graph</a></p>
          </article>
          <p className="meta" style={{ marginTop: 16 }}>Source: results/explorer.json and results/summary.json, demo relation 8512; costs rounded to three decimals.</p>
        </div>
      </section>

      <section className="band-blue">
        <div className="wrap">
          <h2>Fewer wrong verdicts on held-out checks</h2>
          <p className="meta" style={{ marginTop: 12 }}>{held ? `Zenodo 16440960 gold · ${held.toLocaleString("en-US")} held-out checks · 3 seeds` : "Loading the export"}</p>
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
          <h2>Can’t be fooled by a bad feed</h2>
          <p style={{ maxWidth: 640, marginTop: 16 }}>
            In the poisoning test, new reviews falsely call NVD wrong and a modeled mirror right. The guard checks the proposal against earlier reviews and rolls it back when accuracy falls.
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
          <h2>For scanner vendors and security teams</h2>
          <p style={{ maxWidth: 680, marginTop: 16 }}>Proposed go-to-market: expose feed trust where alerts are triaged, and publish the evidence behind each verdict.</p>
          <div className="steps" style={{ marginTop: 28 }}>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>SCA feed-trust API</h3>
              <p style={{ marginTop: 8 }}>A feed-trust API would give SCA vendors and platform teams a verdict with its source path and cost.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>Weekly leaderboard</h3>
              <p style={{ marginTop: 8 }}>A public weekly feed-trust leaderboard would show where each source earns trust by project.</p>
            </article>
            <article className="nb" style={{ padding: 18 }}>
              <h3 className="display" style={{ fontSize: 28 }}>Free GitHub Action</h3>
              <p style={{ marginTop: 8 }}>A free GitHub Action would annotate scanner alerts with the trust verdict and the feeds behind it.</p>
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
            <a className="sq" href="/graph" style={{ background: "#d6ff4a" }} onClick={(event) => { event.preventDefault(); navigate("/graph"); }}>Open the 3D graph</a>
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
