import { useEffect, useState } from "react";
import Chart, { LABELS } from "./Chart.jsx";

const SOURCE_COLOR = {
  wikidata: "#7aa2f7",
  registry: "#e2a15a",
  scraper: "#e15d5d",
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
  };
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.12em] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Card({ children, className = "" }) {
  return <section className={`rounded-xl border border-line bg-card p-4 sm:p-5 ${className}`}>{children}</section>;
}

function Mark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <rect x="1" y="1" width="26" height="26" rx="7" fill="#14181f" stroke="#3cbfa8" />
      <path d="M7 18.5 12 9l4 6 2.5-3.5L21 18.5" fill="none" stroke="#e2a15a" strokeWidth="1.6" />
      <circle cx="12" cy="9" r="1.4" fill="#3cbfa8" />
    </svg>
  );
}

export default function App() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState({});
  const [rel, setRel] = useState(null);
  const [mode, setMode] = useState("dreamgraph");
  const [query, setQuery] = useState(null);
  const [queryError, setQueryError] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [seedFilter, setSeedFilter] = useState("all");
  const [liveLoad, setLiveLoad] = useState(null);
  const [liveBusy, setLiveBusy] = useState(false);

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
        const first = body.demo?.questions?.[0];
        setRel(first ?? null);
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
    if (rel == null) return undefined;
    let cancelled = false;
    setQueryLoading(true);
    setQueryError("");
    fetch(`/api/query?rel=${rel}&mode=${mode}`)
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
        if (!cancelled) setQueryError(err.message || "Query failed");
      })
      .finally(() => {
        if (!cancelled) setQueryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [rel, mode]);

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
            <div key={index} className="h-24 animate-pulse rounded-xl border border-line bg-card" />
          ))}
        </div>
      </main>
    );
  }

  if (error || !results) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16">
        <Card>
          <p className="text-xs uppercase tracking-[0.14em] text-accent">No benchmark export</p>
          <h1 className="mt-2 text-2xl font-semibold">DreamGraph has nothing to chart yet</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            {error || "results/summary.json is missing."} The dashboard does not invent accuracies.
            From the repo root, run <code className="text-ink">make bench</code> and reload.
          </p>
        </Card>
      </main>
    );
  }

  const dream = results.series.dreamgraph;
  const last = dream.accuracy.length - 1;
  const driftIndex = results.drift_iter - 1;
  const load = liveLoad || results.load;
  const policies = results.policies
    .filter((version) => seedFilter === "all" || String(version.seed) === seedFilter)
    .slice()
    .sort((a, b) => Number(b.rolled_back) - Number(a.rolled_back) || a.version - b.version);
  const rollbackTotal = results.policies.filter((version) => version.rolled_back).length;

  const stats = [
    {
      label: "After the window refits",
      value: pct(dream.accuracy[last]),
      detail: `95% CI ${pct(dream.ci_low[last])}–${pct(dream.ci_high[last])}`,
    },
    {
      label: `At drift, iteration ${results.drift_iter}`,
      value: pct(dream.accuracy[driftIndex]),
      detail: "Scored before that iteration's update",
    },
    {
      label: "Unweighted, every iteration",
      value: pct(results.series.unweighted.accuracy[0]),
      detail: "Tie break on node ids, drift-stable",
    },
    {
      label: "Hand-set costs after drift",
      value: pct(results.series.hand_set.accuracy[last]),
      detail: `Started at ${pct(results.series.hand_set.accuracy[0])}`,
    },
  ];

  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex gap-3">
            <Mark />
            <div>
              <h1 className="text-xl font-semibold tracking-tight">DreamGraph</h1>
              <p className="mt-1 max-w-xl text-sm leading-6 text-muted">
                Ownership paths that relearn when a vendor’s labels flip. For compliance teams merging KYC and B2B entity graphs across Wikidata, a registry, and a scraper.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 sm:justify-end">
            <Pill tone="warn">Synthetic source noise</Pill>
            <Pill tone={results.backend === "hydradb" ? "ok" : "neutral"}>
              {results.backend === "hydradb" ? "HydraDB SSpaths" : "In-process graph"}
            </Pill>
            <Pill tone={results.hydra_verified ? "ok" : "warn"}>
              {results.hydra_verified ? "HydraDB verified" : "HydraDB unverified"}
            </Pill>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <Card key={stat.label}>
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted">{stat.label}</p>
              <p className="tabular mt-2 font-mono text-3xl text-ink">{stat.value}</p>
              <p className="mt-1 text-xs text-muted">{stat.detail}</p>
            </Card>
          ))}
        </div>

        <Card>
          <div className="mb-2 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-base font-semibold">Held-out accuracy</h2>
              <p className="text-sm text-muted">
                {results.config.held_out} questions, {results.config.seeds.length} seeds. Bands are bootstrap 95% intervals. The marker is the label swap. After recovery, DreamGraph’s answers are 3-hop paths; unweighted stays on 2 hops.
              </p>
            </div>
            <p className="text-xs text-muted">Precomputed export · {results.generated_at}</p>
          </div>
          <Chart
            series={results.series}
            driftIter={results.drift_iter}
            hidden={hidden}
            onToggle={(method) => setHidden((current) => ({ ...current, [method]: !current[method] }))}
          />
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <caption className="sr-only">Accuracy by method and iteration</caption>
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Method</th>
                  {dream.accuracy.map((_, index) => (
                    <th key={index} className="px-1 py-1 text-right font-medium">{index + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.keys(LABELS).map((method) => (
                  <tr key={method} className="border-t border-line">
                    <th className="py-1.5 pr-3 font-medium text-ink">{LABELS[method]}</th>
                    {results.series[method].accuracy.map((value, index) => (
                      <td key={index} className="tabular px-1 py-1.5 text-right font-mono text-muted">
                        {(value * 100).toFixed(1)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-semibold">Which owner does the path name?</h2>
                <p className="text-sm text-muted">algo.SSpaths on the live node, from the saved edge costs. Not a stored answer.</p>
              </div>
              <div className="inline-flex rounded-lg border border-line bg-bg p-0.5" role="group" aria-label="Path mode">
                {[
                  ["unweighted", "Unweighted"],
                  ["dreamgraph", "DreamGraph"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={mode === value}
                    onClick={() => setMode(value)}
                    className={`rounded-md px-3 py-1.5 text-sm ${mode === value ? "bg-card text-ink" : "text-muted"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="mt-4 block text-xs uppercase tracking-[0.12em] text-muted" htmlFor="relation">
              Company
            </label>
            <select
              id="relation"
              className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm"
              value={rel ?? ""}
              onChange={(event) => setRel(Number(event.target.value))}
            >
              {(results.demo.questions || []).map((id) => (
                <option key={id} value={id}>
                  Northwind {id}
                  {results.demo.disagree?.includes(id) ? " · modes disagree" : ""}
                </option>
              ))}
            </select>
            {queryLoading && <p className="mt-4 text-sm text-muted">Walking the graph…</p>}
            {queryError && <p className="mt-4 text-sm text-danger">{queryError}</p>}
            {query && !queryLoading && (
              <div className="mt-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${query.correct ? "bg-teal/15 text-teal" : "bg-danger/15 text-danger"}`}>
                    {query.correct ? "Names the true owner" : "Names someone else"}
                  </span>
                  <span className="text-xs text-muted">
                    Gold record {query.gold_name} · weight {query.weight}
                  </span>
                </div>
                <div className="flex items-center gap-2 overflow-x-auto pb-2">
                  {query.path.map((node, index) => (
                    <div key={`${node.id}-${index}`} className="flex items-center gap-2">
                      <div className="min-w-[9rem] rounded-lg border border-line bg-bg px-3 py-2">
                        <p className="text-[10px] uppercase tracking-[0.12em] text-muted">{node.kind}</p>
                        <p className="text-sm">{node.name}</p>
                      </div>
                      {query.edges[index] && (
                        <span
                          className="text-[10px] uppercase tracking-[0.14em]"
                          style={{ color: SOURCE_COLOR[query.edges[index].source] || "#8b97a8" }}
                        >
                          {query.edges[index].source}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <ul className="mt-3 space-y-1 text-sm">
                  {query.alternatives.map((alt) => (
                    <li key={alt.source} className="flex items-center justify-between gap-3 text-muted">
                      <span style={{ color: SOURCE_COLOR[alt.source] }}>
                        {alt.source}
                        {alt.chosen ? " · chosen" : ""}
                      </span>
                      <span className="text-right text-ink">
                        {alt.person_name}
                        {alt.correct ? " · true owner" : ""}
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
                <h2 className="text-base font-semibold">Policy versions</h2>
                <p className="text-sm text-muted">
                  {rollbackTotal === 0
                    ? "The guard accepted every refit in this run."
                    : `${rollbackTotal} rollback${rollbackTotal === 1 ? "" : "s"} when the guard slice got worse.`}
                </p>
              </div>
              <select
                aria-label="Seed filter"
                className="rounded-lg border border-line bg-bg px-2 py-1 text-sm"
                value={seedFilter}
                onChange={(event) => setSeedFilter(event.target.value)}
              >
                <option value="all">All seeds</option>
                {results.config.seeds.map((seed) => (
                  <option key={seed} value={String(seed)}>Seed {seed}</option>
                ))}
              </select>
            </div>
            <ol className="mt-4 max-h-[28rem] space-y-2 overflow-y-auto pr-1">
              {policies.map((version) => (
                <li
                  key={version.version}
                  className={`rounded-lg border px-3 py-2 ${version.rolled_back ? "border-danger/60" : "border-line"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm">
                      Iteration {version.iteration}
                      <span className="text-muted"> · seed {version.seed}</span>
                    </p>
                    <span className={`text-[11px] uppercase tracking-[0.12em] ${version.rolled_back ? "text-danger" : "text-teal"}`}>
                      {version.rolled_back ? "Rolled back" : "Accepted"}
                    </span>
                  </div>
                  <p className="tabular mt-1 font-mono text-xs text-muted">
                    wiki {version.costs.wikidata.toFixed(2)} · reg {version.costs.registry.toFixed(2)} · scrap {version.costs.scraper.toFixed(2)}
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    Window {version.window}
                    {version.guard_accuracy == null ? "" : ` · guard ${pct(version.guard_accuracy)}`}
                    {version.rolled_back ? ` · ${version.reason}` : ""}
                  </p>
                </li>
              ))}
              {policies.length === 0 && <li className="text-sm text-muted">No versions for this seed.</li>}
            </ol>
          </Card>
        </div>

        <Card>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-base font-semibold">Search latency</h2>
              <p className="max-w-2xl text-sm text-muted">{load.what}</p>
            </div>
            <button
              type="button"
              onClick={remeasure}
              disabled={liveBusy}
              className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink disabled:opacity-50"
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
              <div key={label} className="rounded-lg border border-line bg-bg px-4 py-3">
                <p className="text-[11px] uppercase tracking-[0.14em] text-muted">{label}</p>
                <p className="tabular mt-1 font-mono text-2xl">{msLabel(value)}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            n = {load.n}. {liveLoad ? "This panel is a live remeasure." : "This panel is the benchmark sample."} HydraDB round-trip time is not in this file.
          </p>
        </Card>
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs leading-5 text-muted">
        Source noise is synthetic. The 3-hop chain names the true owner {pct(results.noise?.chain_p_true?.long)} of the time, the short trap {pct(results.noise?.chain_p_true?.trap)}, and the other short chain {pct(results.noise?.chain_p_true?.alt)}. Iteration {results.drift_iter} exchanges the wikidata and scraper labels. DreamGraph asks HydraDB for the minimum summed-cost path. The dict learner minimizes that same sum in process
        {results.series.dict_learner.accuracy.every((value, index) => value === results.series.dreamgraph.accuracy[index])
          ? " and matched these accuracies."
          : "."}{" "}
        Unweighted never takes the 3-hop chain. {results.notes?.[1]}
      </footer>
    </div>
  );
}
