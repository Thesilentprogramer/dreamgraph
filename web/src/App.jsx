import { lazy, Suspense, useEffect, useState } from "react";
import Chart, { LABELS } from "./Chart.jsx";

const Explorer = lazy(() => import("./explorer/Explorer.jsx"));

const GITHUB = "https://github.com/Thesilentprogramer/dreamgraph";

const SOURCE_COLOR = {
  wikidata: "#7aa2f7",
  registry: "#e2a15a",
  scraper: "#f07178",
  nvd: "#38bdf8",
  nvd_mirror: "#fb7185",
  debian: "#e2a15a",
  alpine: "#3cbfa8",
  linux: "#a3e635",
  redhat: "#f07178",
  suse: "#c4b5fd",
  opensuse: "#d7c07a",
  alma: "#94a3b8",
  mageia: "#f9a8d4",
  rocky: "#fdba74",
};

function pct(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function msLabel(value) {
  if (value == null) return "—";
  if (value < 0.1) return `${(value * 1000).toFixed(1)} µs`;
  return `${value.toFixed(2)} ms`;
}

function Pill({ children, tone = "neutral" }) {
  const tones = {
    neutral: "border-line text-muted",
    warn: "border-accent/50 text-accent",
    ok: "border-teal/50 text-teal",
    bad: "border-danger/50 text-danger",
  };
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.14em] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Card({ children, className = "" }) {
  return <section className={`card p-4 sm:p-5 ${className}`}>{children}</section>;
}

function Mark() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="9" fill="#121722" stroke="#3cbfa8" />
      <path d="M8 21.5 13.2 10l4.2 6.4 2.6-3.6L24 21.5" fill="none" stroke="#e2a15a" strokeWidth="1.7" />
      <circle cx="13.2" cy="10" r="1.6" fill="#3cbfa8" />
    </svg>
  );
}

function last(series) {
  return series.accuracy.length - 1;
}

export default function App() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState({});
  const [rel, setRel] = useState(null);
  const [mode, setMode] = useState("dreamgraph");
  const [dataset, setDataset] = useState("synthetic");
  const [queryDataset, setQueryDataset] = useState("synthetic");
  const [query, setQuery] = useState(null);
  const [queryError, setQueryError] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [seedFilter, setSeedFilter] = useState("all");
  const [liveLoad, setLiveLoad] = useState(null);
  const [liveBusy, setLiveBusy] = useState(false);
  const [engine, setEngine] = useState(null);
  const [screen, setScreen] = useState("dash");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/results")
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `Results request failed (${response.status})`);
        }
        return response.json();
      })
      .then((body) => {
        if (cancelled) return;
        setResults(body);
        setRel(body.demo?.questions?.[0] ?? null);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load results");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) return;
        const body = await response.json();
        if (!cancelled) setEngine(body);
      } catch {
        if (!cancelled) setEngine({ live_engine: false, hydradb: false });
      }
    }
    poll();
    const timer = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!results) return;
    const next = queryDataset === "vuln" ? results.vuln?.demo?.questions?.[0] : results.demo?.questions?.[0];
    setRel(next ?? null);
    setQuery(null);
    setQueryError("");
  }, [queryDataset, results]);

  useEffect(() => {
    if (rel == null || !results) return undefined;
    const allowed =
      queryDataset === "vuln" ? results.vuln?.demo?.questions || [] : results.demo?.questions || [];
    if (!allowed.includes(rel)) return undefined;
    let cancelled = false;
    setQueryLoading(true);
    setQueryError("");
    fetch(`/api/query?rel=${rel}&mode=${mode}&dataset=${queryDataset}`)
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `Query failed (${response.status})`);
        }
        return response.json();
      })
      .then((body) => {
        if (!cancelled) setQuery(body);
      })
      .catch((err) => {
        if (!cancelled) {
          setQuery(null);
          setQueryError(err.message || "Query failed");
        }
      })
      .finally(() => {
        if (!cancelled) setQueryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [rel, mode, queryDataset, results]);

  async function remeasure() {
    setLiveBusy(true);
    try {
      const response = await fetch("/api/load?live=1");
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Load measure failed");
      setLiveLoad(body.live);
    } catch (err) {
      setQueryError(err.message || "Load measure failed");
    } finally {
      setLiveBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-10">
        <p className="text-sm text-muted">Loading the benchmark export…</p>
        <div className="mt-6 grid gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-28 animate-pulse rounded-2xl border border-line bg-card" />
          ))}
        </div>
      </main>
    );
  }

  if (error || !results) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16">
        <Card>
          <p className="eyebrow">No benchmark export</p>
          <h1 className="mt-2 font-serif text-3xl">DreamGraph has nothing to chart yet</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            {error || "results/summary.json is missing."} The dashboard does not invent accuracies. From the repo root, run{" "}
            <code className="text-ink">make bench</code> and reload.
          </p>
        </Card>
      </main>
    );
  }

  const vuln = results.vuln;
  const poison = results.vuln_poison;
  const hypotheses = results.hypotheses || [];
  const view =
    dataset === "vuln" && vuln?.series
      ? vuln
      : dataset === "poison" && poison?.series
        ? poison
        : results;
  const series = view.series;
  const dream = series.dreamgraph;
  const end = last(dream);
  const markers =
    dataset === "poison" && poison
      ? [{ iter: poison.poison_iter, label: "Poison", color: "#f07178" }]
      : dataset === "vuln" && vuln
        ? [{ iter: vuln.drift_iter || 4, label: vuln.drift?.kind === "real" ? "Newer feeds" : "Simulated", color: "#e2a15a" }]
        : dataset === "synthetic"
          ? [{ iter: results.drift_iter, label: "Drift", color: "#e2a15a" }]
          : [];
  const load = liveLoad || results.load;
  const policySource =
    dataset === "poison" ? poison?.policies || poison?.receipts || [] : dataset === "vuln" ? vuln?.policies || [] : results.policies;
  const policies = policySource
    .filter((version) => seedFilter === "all" || String(version.seed) === seedFilter)
    .slice()
    .sort((a, b) => Number(b.rolled_back) - Number(a.rolled_back) || a.iteration - b.iteration || a.seed - b.seed);
  const rollbackTotal =
    dataset === "poison"
      ? poison.rollback_count
      : policySource.filter((version) => version.rolled_back).length;
  const questions =
    queryDataset === "vuln" ? vuln?.demo?.questions || [] : results.demo.questions || [];
  const labels = queryDataset === "vuln" ? vuln?.demo?.labels || {} : null;
  const oneHop = results.series.one_hop;
  const passes = hypotheses.filter((item) => item.verdict === "PASS").length;

  const stats = [
    {
      label: "Synthetic full path, iter 8",
      value: pct(results.series.dreamgraph.accuracy.at(-1)),
      detail: `95% CI ${pct(results.series.dreamgraph.ci_low.at(-1))}–${pct(results.series.dreamgraph.ci_high.at(-1))}`,
    },
    {
      label: "1-hop lookup, same costs",
      value: oneHop ? pct(oneHop.accuracy.at(-1)) : "—",
      detail: oneHop ? `95% CI ${pct(oneHop.ci_low.at(-1))}–${pct(oneHop.ci_high.at(-1))}` : "Replay missing",
    },
    {
      label: "Vuln feeds, held out",
      value: vuln ? pct(vuln.series.dreamgraph.accuracy.at(-1)) : "—",
      detail: vuln
        ? `95% CI ${pct(vuln.series.dreamgraph.ci_low.at(-1))}–${pct(vuln.series.dreamgraph.ci_high.at(-1))} · ${vuln.config.held_out} tags`
        : "Slice missing",
    },
    {
      label: "NVD-mirror rollbacks",
      value: poison ? String(poison.rollback_count) : "0",
      detail: poison
        ? `From iteration ${poison.poison_iter}. ${Object.entries(poison.rollback_counts || {})
            .filter(([, count]) => count === 0)
            .map(([seed]) => `Seed ${seed} accepted the poisoned update.`)
            .join(" ")}`
        : "No poison scenario",
    },
  ];

  const ablationRows =
    dataset === "poison"
      ? ["dreamgraph", "naive", "greedy", "frozen_at_3", "dict_learner", "one_hop", "unweighted"]
      : dataset === "vuln"
        ? ["dreamgraph", "majority", "nvd_only", "unweighted", "hand_set", "bm25", "ghsa_only", "dict_learner", "one_hop", "frozen_at_3", "greedy"]
        : ["dreamgraph", "one_hop", "unweighted", "dict_learner"];

  const ablationNote =
    dataset === "vuln"
      ? "Each feed is a two-edge chain, so a 1-hop lookup and the full sum rank the same feed. Majority vote lets the noisy distros outvote NVD. GHSA has no version ranges here, so that baseline abstains and is scored as not-affected. The learned costs are what HydraDB’s weighted path search consumes."
      : dataset === "poison"
        ? "From iteration 4, train reviews call wikidata wrong and scraper right. Held-out people stay put. Naive accepts the lie. The guard scores the proposal on the last 20 window questions against the true owner and rolls back."
        : "1-hop lookup spends the learned cost of the first edge only and never calls algo.SSpaths. Unweighted search counts hops. DreamGraph sums the learned costs; this synthetic run did that sum inside HydraDB. The dict learner sums the same costs in process, so the accuracies match. The gap that is not zero is the path sum versus a single edge.";

  return (
    <div className="min-h-screen">
      {screen === "graph" && (
        <Suspense fallback={<div className="fixed inset-0 z-40 bg-[#0a0a0a] p-8 text-sm text-white">Loading the 3D graph…</div>}>
          <Explorer onClose={() => setScreen("dash")} />
        </Suspense>
      )}
      <header className="border-b border-line/80">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <Mark />
            <div>
              <p className="text-sm font-medium tracking-tight">DreamGraph</p>
              <p className="text-xs text-muted">HydraDB Track 1</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={engine?.seeding ? "warn" : engine?.live_engine ? "ok" : "warn"}>
              {engine?.seeding ? "Seeding HydraDB" : engine?.live_engine ? "Live engine" : "Engine down"}
            </Pill>
            <Pill tone={results.hydra_verified ? "ok" : "warn"}>
              {results.hydra_verified ? "Benchmark on HydraDB" : "Benchmark unverified"}
            </Pill>
            <button
              type="button"
              onClick={() => setScreen("graph")}
              className="rounded-full border border-line px-3 py-1 text-xs text-ink transition hover:border-teal/50"
            >
              3D graph
            </button>
            <a
              href={GITHUB}
              className="rounded-full border border-line px-3 py-1 text-xs text-ink transition hover:border-teal/50"
            >
              GitHub
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-6">
        <section className="rise">
          <p className="eyebrow">Self-improving multi-vendor graph</p>
          <h1 className="mt-3 max-w-3xl font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
            The path cost learns which source to trust.
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            When NVD and the distro feeds disagree on what is actually vulnerable, DreamGraph learns which source to trust, and HydraDB’s weighted path search uses those costs to answer. A bad update is rolled back when it loses on the guard slice.
          </p>
        </section>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat, index) => (
            <Card key={stat.label} className="rise" style={{ animationDelay: `${index * 40}ms` }}>
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted">{stat.label}</p>
              <p className="tabular mt-2 font-mono text-3xl text-ink">{stat.value}</p>
              <p className="mt-1 text-xs leading-5 text-muted">{stat.detail}</p>
            </Card>
          ))}
        </div>

        <Card>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="font-serif text-2xl">Held-out accuracy</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">
                {dataset === "vuln"
                  ? `${vuln.config.held_out} held-out tags, ${vuln.config.seeds.length} seeds. Batches follow feed modified times. Drift here is ${vuln.drift?.kind}.`
                  : dataset === "poison"
                    ? `${poison.config.held_out} tags, ${poison.config.seeds.length} seeds. The marker is when reviews start trusting the bad NVD mirror.`
                    : `${results.config.held_out} questions, ${results.config.seeds.length} seeds. The marker is the wikidata/scraper label swap, scored before that iteration’s update.`}
              </p>
            </div>
            <div className="inline-flex rounded-full border border-line bg-bg p-0.5" role="tablist" aria-label="Chart dataset">
              {[
                ["synthetic", "Synthetic"],
                ["vuln", "Vuln feeds"],
                ["poison", "Poison"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={dataset === value}
                  onClick={() => setDataset(value)}
                  className={`rounded-full px-3 py-1.5 text-sm transition ${dataset === value ? "bg-card text-ink" : "text-muted"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <Chart
            series={series}
            markers={markers}
            hidden={hidden}
            onToggle={(method) => setHidden((current) => ({ ...current, [method]: !current[method] }))}
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <caption className="sr-only">Accuracy by method and iteration</caption>
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Method</th>
                  {dream.accuracy.map((_, index) => (
                    <th key={index} className={`px-1 py-1 text-right font-medium ${markers.some((pin) => pin.iter === index + 1) ? "text-accent" : ""}`}>
                      {index + 1}
                    </th>
                  ))}
                  <th className="px-1 py-1 text-right font-medium">Final CI</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(series)
                  .filter((method) => LABELS[method])
                  .map((method) => (
                    <tr key={method} className="border-t border-line">
                      <th className="py-1.5 pr-3 font-medium text-ink">{LABELS[method]}</th>
                      {series[method].accuracy.map((value, index) => (
                        <td key={index} className="tabular px-1 py-1.5 text-right font-mono text-muted">
                          {(value * 100).toFixed(1)}
                        </td>
                      ))}
                      <td className="tabular px-1 py-1.5 text-right font-mono text-muted">
                        {pct(series[method].ci_low?.[end])}–{pct(series[method].ci_high?.[end])}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <h2 className="font-serif text-2xl">Ablations</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">{ablationNote}</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.12em] text-muted">
                <tr>
                  <th className="py-2 pr-3 font-medium">Arm</th>
                  <th className="py-2 pr-3 text-right font-medium">Final</th>
                  <th className="py-2 text-right font-medium">3-hop rate</th>
                </tr>
              </thead>
              <tbody>
                {ablationRows.filter((method) => series[method]).map((method) => (
                  <tr key={method} className="border-t border-line">
                    <th className="py-2 pr-3 text-left font-medium text-ink">{LABELS[method] || method}</th>
                    <td className="tabular py-2 pr-3 text-right font-mono">{pct(series[method].accuracy.at(-1))}</td>
                    <td className="tabular py-2 text-right font-mono text-muted">
                      {series[method].hop3_rate ? series[method].hop3_rate.at(-1).toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {vuln?.source_table && (
          <Card>
            <h2 className="font-serif text-2xl">Learned trust versus measured accuracy</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
              Cost is the mean final DreamGraph weight. Lower means the path search trusts that feed. Accuracy is the feed’s agreement with the Zenodo label on this slice, not a feature the learner was given. {vuln.drift?.note}
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="text-xs uppercase tracking-[0.12em] text-muted">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Feed</th>
                    <th className="py-2 pr-3 text-right font-medium">Learned cost</th>
                    <th className="py-2 pr-3 text-right font-medium">Accuracy</th>
                    <th className="py-2 text-right font-medium">Judgments</th>
                  </tr>
                </thead>
                <tbody>
                  {[...vuln.source_table]
                    .sort((a, b) => a.learned_cost - b.learned_cost)
                    .map((row) => (
                      <tr key={row.source} className="border-t border-line">
                        <th className="py-2 pr-3 text-left font-medium" style={{ color: SOURCE_COLOR[row.source] || undefined }}>
                          {row.source}
                        </th>
                        <td className="tabular py-2 pr-3 text-right font-mono">{row.learned_cost.toFixed(3)}</td>
                        <td className="tabular py-2 pr-3 text-right font-mono">{pct(row.accuracy)}</td>
                        <td className="tabular py-2 text-right font-mono text-muted">{row.n}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        <Card>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-serif text-2xl">Pre-registered hypotheses</h2>
              <p className="mt-1 text-sm text-muted">
                {passes} of {hypotheses.length} passed. Verdicts are computed from the evidence files, not typed in.
              </p>
            </div>
          </div>
          <ol className="mt-4 space-y-2">
            {hypotheses.map((item) => (
              <li key={item.id} className="grid gap-2 rounded-xl border border-line px-3 py-3 sm:grid-cols-[4.5rem_1fr_auto] sm:items-start">
                <p className="font-mono text-sm text-muted">{item.id}</p>
                <div>
                  <p className="text-sm leading-6">{item.statement}</p>
                  <p className="mt-1 font-mono text-xs text-muted">{item.observed}</p>
                </div>
                <Pill tone={item.verdict === "PASS" ? "ok" : "bad"}>{item.verdict}</Pill>
              </li>
            ))}
            {hypotheses.length === 0 && <li className="text-sm text-muted">No hypothesis file in this export.</li>}
          </ol>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-serif text-2xl">Live path</h2>
                <p className="text-sm text-muted">algo.SSpaths on the running node. The answer is not stored in the page.</p>
              </div>
              <div className="inline-flex rounded-full border border-line bg-bg p-0.5" role="group" aria-label="Path mode">
                {[
                  ["unweighted", "Unweighted"],
                  ["dreamgraph", "DreamGraph"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={mode === value}
                    onClick={() => setMode(value)}
                    className={`rounded-full px-3 py-1.5 text-sm ${mode === value ? "bg-card text-ink" : "text-muted"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[
                ["synthetic", "Ownership gadget"],
                ["vuln", "CVE tag"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={queryDataset === value}
                  onClick={() => setQueryDataset(value)}
                  className={`rounded-full border px-3 py-1 text-xs ${queryDataset === value ? "border-teal/50 text-teal" : "border-line text-muted"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="mt-4 block text-xs uppercase tracking-[0.12em] text-muted" htmlFor="relation">
              {queryDataset === "vuln" ? "Package tag" : "Company"}
            </label>
            <select
              id="relation"
              className="mt-1 w-full rounded-xl border border-line bg-bg px-3 py-2 text-sm"
              value={rel ?? ""}
              onChange={(event) => setRel(Number(event.target.value))}
            >
              {questions.map((id) => (
                <option key={id} value={id}>
                  {labels ? labels[String(id)] || `Question ${id}` : `Northwind ${id}`}
                  {queryDataset === "synthetic" && results.demo.disagree?.includes(id) ? " · modes disagree" : ""}
                </option>
              ))}
            </select>
            {queryDataset === "vuln" && (
              <p className="mt-2 text-xs leading-5 text-muted">
                Live algo.SSpaths on this tag. The chain is question, claim, verdict.
              </p>
            )}
            {queryLoading && <p className="mt-4 text-sm text-muted">Walking the graph…</p>}
            {queryError && <p className="mt-4 text-sm text-danger">{queryError}</p>}
            {query && !queryLoading && (
              <div className="mt-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${query.correct ? "bg-teal/15 text-teal" : "bg-danger/15 text-danger"}`}>
                    {query.correct ? "Matches gold" : "Does not match gold"}
                  </span>
                  <span className="text-xs text-muted">
                    Gold {query.gold_name} · weight {query.weight} · {query.procedure}
                  </span>
                </div>
                <div className="flex items-center gap-2 overflow-x-auto pb-2">
                  {query.path.map((node, index) => (
                    <div key={`${node.id}-${index}`} className="path-node flex items-center gap-2" style={{ animationDelay: `${index * 70}ms` }}>
                      <div className="min-w-[9.5rem] rounded-xl border border-line bg-bg px-3 py-2">
                        <p className="text-[10px] uppercase tracking-[0.12em] text-muted">{node.kind}</p>
                        <p className="text-sm leading-5">{node.name}</p>
                      </div>
                      {query.edges[index] && (
                        <span
                          className="max-w-[6.5rem] text-[10px] uppercase leading-4 tracking-[0.08em]"
                          style={{ color: SOURCE_COLOR[query.edges[index].source] || "#93a0b5" }}
                        >
                          {query.edges[index].source}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <ul className="mt-3 space-y-1 text-sm">
                  {query.alternatives.map((alt) => (
                    <li key={`${alt.label}-${alt.person}`} className="flex items-center justify-between gap-3 text-muted">
                      <span style={{ color: SOURCE_COLOR[alt.label] || SOURCE_COLOR[alt.source] || "#93a0b5" }}>
                        {alt.label || alt.source}
                        {alt.chosen ? " · chosen" : ""}
                        {` · ${alt.hops} hop${alt.hops === 1 ? "" : "s"}`}
                      </span>
                      <span className="text-right text-ink">
                        {alt.person_name}
                        {alt.correct ? " · gold" : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <Card>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-serif text-2xl">Guard receipts</h2>
                <p className="text-sm text-muted">
                  {rollbackTotal === 0
                    ? "The guard accepted every refit in this view. Switch the chart to Poison to read the rollback receipts."
                    : `${rollbackTotal} rollback${rollbackTotal === 1 ? "" : "s"}. A receipt keeps the metric before and after the proposal.`}
                </p>
              </div>
              <select
                aria-label="Seed filter"
                className="rounded-xl border border-line bg-bg px-2 py-1 text-sm"
                value={seedFilter}
                onChange={(event) => setSeedFilter(event.target.value)}
              >
                <option value="all">All seeds</option>
                {(view.config?.seeds || results.config.seeds).map((seed) => (
                  <option key={seed} value={String(seed)}>
                    Seed {seed}
                  </option>
                ))}
              </select>
            </div>
            <ol className="mt-4 max-h-[32rem] space-y-2 overflow-y-auto pr-1">
              {policies.map((version) => (
                <li
                  key={`${version.version}-${version.seed}-${version.iteration}`}
                  className={`rounded-xl border px-3 py-2 ${version.rolled_back ? "border-danger/60 bg-danger/5" : "border-line"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm">
                      v{version.version} · iteration {version.iteration}
                      <span className="text-muted"> · seed {version.seed}</span>
                    </p>
                    <span className={`text-[11px] uppercase tracking-[0.12em] ${version.rolled_back ? "text-danger" : "text-teal"}`}>
                      {version.rolled_back ? "Rolled back" : "Accepted"}
                    </span>
                  </div>
                  <p className="tabular mt-1 font-mono text-xs text-muted">
                    {Object.entries(version.costs)
                      .map(([name, value]) => `${name} ${Number(value).toFixed(2)}`)
                      .join(" · ")}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    Window {version.window}
                    {version.guard_before == null ? "" : ` · guard ${pct(version.guard_before)} → ${pct(version.guard_after)}`}
                    {version.heldout_before == null ? "" : ` · held-out ${pct(version.heldout_before)} → ${pct(version.heldout_after)}`}
                    {version.reason ? ` · ${version.reason}` : ""}
                  </p>
                </li>
              ))}
              {policies.length === 0 && <li className="text-sm text-muted">No versions for this view.</li>}
            </ol>
          </Card>
        </div>

        <Card>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="font-serif text-2xl">Search latency</h2>
              <p className="max-w-2xl text-sm text-muted">{load.what}</p>
            </div>
            <button
              type="button"
              onClick={remeasure}
              disabled={liveBusy}
              className="rounded-full border border-line px-3 py-1.5 text-sm text-ink transition hover:border-teal/50 disabled:opacity-50"
            >
              {liveBusy ? "Measuring…" : "Measure again"}
            </button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              ["p50", load.p50_ms],
              ["p95", load.p95_ms],
              ["p99", load.p99_ms],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-line bg-bg px-4 py-3">
                <p className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</p>
                <p className="tabular mt-1 font-mono text-2xl">{msLabel(value)}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            n = {load.n}
            {load.clients ? ` · ${load.clients} clients` : ""}. {liveLoad ? "This panel is a live remeasure." : "This panel is the benchmark sample."}
          </p>
        </Card>
      </main>
      <footer className="mx-auto flex max-w-6xl flex-col gap-2 px-4 pb-10 text-xs leading-5 text-muted">
        <p>
          Synthetic noise is labeled as such. Vulnerability numbers use the Zenodo 16440960 gold tags and the processed feeds in{" "}
          <span className="text-ink">data/vuln/claims.jsonl</span>. The dict learner matches DreamGraph where both minimize the same edge-cost sum. HydraDB is the engine that evaluates that sum on the live path.
        </p>
        <p>
          <a className="text-ink underline decoration-line underline-offset-2" href={GITHUB}>
            {GITHUB}
          </a>
        </p>
      </footer>
    </div>
  );
}
