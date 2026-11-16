import { lazy, Suspense, useEffect, useState } from "react";
import Chart, { LABELS } from "./Chart.jsx";

const Explorer = lazy(() => import("./explorer/Explorer.jsx"));

const GITHUB = "https://github.com/Thesilentprogramer/dreamgraph";

function pct(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function msLabel(value) {
  if (value == null) return "—";
  if (value < 0.1) return `${(value * 1000).toFixed(1)} µs`;
  return `${value.toFixed(2)} ms`;
}

function last(series) {
  return series.accuracy.length - 1;
}

export default function App() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState({
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
  });
  const [rel, setRel] = useState(null);
  const [mode, setMode] = useState("dreamgraph");
  const [dataset, setDataset] = useState("vuln");
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
      <div className="frame p-8">
        <p className="meta">Loading the benchmark export</p>
      </div>
    );
  }

  if (error || !results) {
    return (
      <div className="frame p-8">
        <p className="meta">No benchmark export</p>
        <h1 className="display display-black mt-4 text-6xl">Nothing to chart</h1>
        <p className="mt-4 max-w-xl text-base leading-7">
          {error || "results/summary.json is missing."} The dashboard does not invent accuracies. From the repo root, run make bench and reload.
        </p>
      </div>
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
      ? [{ iter: poison.poison_iter, label: "POISON" }]
      : dataset === "vuln" && vuln
        ? [{ iter: vuln.drift_iter || 4, label: "NEWER FEEDS" }]
        : dataset === "synthetic"
          ? [{ iter: results.drift_iter, label: "DRIFT" }]
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
  const questions = queryDataset === "vuln" ? vuln?.demo?.questions || [] : results.demo.questions || [];
  const labels = queryDataset === "vuln" ? vuln?.demo?.labels || {} : null;
  const passes = hypotheses.filter((item) => item.verdict === "PASS").length;
  const feeds = vuln?.source_table ? [...vuln.source_table].sort((a, b) => b.accuracy - a.accuracy) : [];
  const spearman = hypotheses.find((item) => item.id === "H4");
  const kpis = [
    {
      value: vuln ? pct(vuln.series.dreamgraph.accuracy.at(-1)) : "—",
      caption: "Vuln held-out",
      invert: true,
    },
    {
      value: pct(results.series.dreamgraph.accuracy.at(-1)),
      caption: "Synthetic path",
    },
    {
      value: vuln ? Number(vuln.config.held_out).toLocaleString("en-US") : "—",
      caption: "Held-out tags",
    },
    {
      value: feeds.length ? String(feeds.length) : "—",
      caption: "Feeds in the slice",
    },
  ];
  const arms =
    dataset === "poison"
      ? ["dreamgraph", "naive", "frozen_at_3", "greedy", "dict_learner", "unweighted"]
      : dataset === "vuln"
        ? ["dreamgraph", "conditional_k1", "topk_open", "per_feed", "nvd_only", "majority", "hand_set", "unweighted", "bm25", "ghsa_only", "frozen_at_3", "dict_learner"]
        : ["dreamgraph", "one_hop", "unweighted", "dict_learner"];
  const winner = arms.filter((method) => series[method]).sort((a, b) => series[b].accuracy.at(-1) - series[a].accuracy.at(-1))[0];

  return (
    <div className="frame">
      {screen === "graph" && (
        <Suspense fallback={<div className="fixed inset-0 z-40 bg-[#F0F2F1] p-8 text-sm text-[#070EF4]">Loading the graph…</div>}>
          <Explorer onClose={() => setScreen("dash")} />
        </Suspense>
      )}
      <div className="px-6 py-5 sm:px-10">
        <div className="flex items-center justify-between gap-4">
          <p className="meta">DreamGraph · HydraDB OSS</p>
          <p className="meta">16 Nov 2026</p>
        </div>
        <div className="mt-8 flex flex-wrap items-end justify-between gap-6">
          <h1 className="display max-w-5xl text-6xl sm:text-8xl">
            <span className="display-thin">Self-improving </span>
            <span className="display-black">graph</span>
            <span className="display-thin"> + trust it</span>
          </h1>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="sq sq-invert" onClick={() => setScreen("graph")}>
              Open the graph
            </button>
            <a className="sq" href={GITHUB}>
              GitHub
            </a>
          </div>
        </div>
        <p className="mt-6 max-w-2xl text-base leading-7">
          When NVD and the distro feeds disagree, DreamGraph learns which source to trust. HydraDB’s weighted path search spends those costs. A proposal that loses the guard is rolled back.
        </p>
        <p className="meta mt-4">{engine?.live_engine ? "Live engine" : engine?.seeding ? "Seeding HydraDB" : "Engine down"} · {passes}/{hypotheses.length || "—"} hypotheses</p>

        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((item) => (
            <div key={item.caption} className={item.invert ? "kpi kpi-invert" : "kpi"}>
              <p className="display display-black text-6xl">{item.value}</p>
              <p className="meta" style={{ color: "inherit" }}>{item.caption}</p>
            </div>
          ))}
        </div>

        <hr className="rule mt-10" />
        <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
          <p className="meta">Accuracy · iteration</p>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Chart dataset">
            {[
              ["vuln", "Vuln feeds"],
              ["synthetic", "Synthetic"],
              ["poison", "Poison"],
            ].map(([value, label]) => (
              <button key={value} type="button" role="tab" aria-selected={dataset === value} onClick={() => setDataset(value)} className={dataset === value ? "sq sq-invert" : "sq"}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-6">
          {dataset === "vuln"
            ? `${vuln.config.held_out} held-out tags, ${vuln.config.seeds.length} seeds. Conditional feed×project costs, top-5 vote within 0.15 of the cheapest verdict path. Drift is ${vuln.drift?.kind}.`
            : dataset === "poison"
              ? "From iteration 4, new reviews call NVD wrong and the mirror right. Earlier reviews stay as logged."
              : `${results.config.held_out} questions, ${results.config.seeds.length} seeds. The block marks the wikidata/scraper label swap.`}
        </p>
        <div className="mt-4">
          <Chart
            series={series}
            markers={markers}
            hidden={hidden}
            onToggle={(method) => setHidden((current) => ({ ...current, [method]: !current[method] }))}
          />
        </div>

        <hr className="rule mt-10" />
        <p className="meta mt-6">Baselines · held out</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {arms.filter((method) => series[method]).map((method) => (
            <div key={method} className={method === winner ? "tile tile-invert" : "tile"}>
              <p className="display display-black text-3xl">{LABELS[method] || method}</p>
              <p className="meta" style={{ color: "inherit" }}>
                {pct(series[method].accuracy.at(-1))} · {pct(series[method].ci_low?.[end])}–{pct(series[method].ci_high?.[end])}
              </p>
            </div>
          ))}
        </div>

        {feeds.length > 0 && (
          <>
            <hr className="rule mt-10" />
            <p className="meta mt-6">Feed trust · measured accuracy</p>
            <div className="mt-4 space-y-3">
              {feeds.map((row) => (
                <div key={row.source} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3">
                  <p className="text-sm">{row.source}</p>
                  <div className="bar-track" aria-hidden="true">
                    <div className="bar-fill" style={{ width: `${Math.max(2, row.accuracy * 100)}%` }} />
                  </div>
                  <p className="meta text-right">{pct(row.accuracy)}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm leading-6">
              Learned feed costs run from {feeds.slice().sort((a, b) => a.learned_cost - b.learned_cost)[0].source} at {feeds.slice().sort((a, b) => a.learned_cost - b.learned_cost)[0].learned_cost.toFixed(3)} to the dearest feed. {spearman ? spearman.observed : "Spearman is computed from the evidence file."} Accuracy here is agreement with Zenodo, not a training feature.
            </p>
          </>
        )}

        <hr className="rule mt-10" />
        <p className="meta mt-6">Key insights</p>
        <ul className="mt-4 space-y-3">
          <li className="insight">
            <span className="insight-mark">→</span>
            <p>Conditional costs beat a single cost per feed. Linux stays cheap where it is perfect. NVD stays the broad default.</p>
          </li>
          <li className="insight">
            <span className="insight-mark">→</span>
            <p>The vote uses the cheapest verdict paths. Paths more than 0.15 above the winner drop out, so a clear specialist is not outvoted.</p>
          </li>
          <li className="insight">
            <span className="insight-mark">→</span>
            <p>
              Poison reviews no longer rewrite history. Rollbacks: {poison ? Object.entries(poison.rollback_counts || {}).map(([seed, count]) => `seed ${seed} × ${count}`).join(", ") : "—"}.
            </p>
          </li>
        </ul>

        <hr className="rule mt-10" />
        <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
          <p className="meta">Hypotheses · {passes} of {hypotheses.length} passed</p>
        </div>
        <ul className="mt-4">
          {hypotheses.map((item) => (
            <li key={item.id} className="grid gap-2 border-t-2 border-[#070EF4] py-3 sm:grid-cols-[4rem_1fr_5rem]">
              <p className="meta">{item.id}</p>
              <div>
                <p className="text-sm leading-6">{item.statement}</p>
                <p className="meta mt-1">{item.observed}</p>
              </div>
              <p className={item.verdict === "PASS" ? "meta bg-[#070EF4] px-2 py-1 text-[#F4F5FA]" : "meta border-2 border-[#070EF4] px-2 py-1"}>{item.verdict}</p>
            </li>
          ))}
        </ul>

        <hr className="rule mt-10" />
        <div className="mt-6 grid gap-10 lg:grid-cols-2">
          <section>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="meta">Live path</p>
              <div className="flex gap-2" role="group" aria-label="Path mode">
                {[
                  ["unweighted", "Unweighted"],
                  ["dreamgraph", "DreamGraph"],
                ].map(([value, label]) => (
                  <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)} className={mode === value ? "sq sq-invert" : "sq"}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-3 flex gap-2">
              {[
                ["synthetic", "Ownership"],
                ["vuln", "CVE tag"],
              ].map(([value, label]) => (
                <button key={value} type="button" aria-pressed={queryDataset === value} onClick={() => setQueryDataset(value)} className={queryDataset === value ? "sq sq-invert" : "sq"}>
                  {label}
                </button>
              ))}
            </div>
            <label className="meta mt-4 block" htmlFor="relation">{queryDataset === "vuln" ? "Package tag" : "Company"}</label>
            <select id="relation" className="mt-2 w-full border-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-2 text-sm" value={rel ?? ""} onChange={(event) => setRel(Number(event.target.value))}>
              {questions.map((id) => (
                <option key={id} value={id}>
                  {labels ? labels[String(id)] || `Question ${id}` : `Relation ${id}`}
                  {queryDataset === "synthetic" && results.demo.disagree?.includes(id) ? " · modes disagree" : ""}
                </option>
              ))}
            </select>
            {queryLoading && <p className="mt-4 text-sm">Walking the graph…</p>}
            {queryError && <p className="mt-4 text-sm">{queryError}</p>}
            {query && !queryLoading && (
              <div className="mt-4">
                <p className="meta">{query.correct ? "Matches gold" : "Does not match gold"} · {query.gold_name} · weight {query.weight} · {query.procedure}</p>
                <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-2">
                  {query.path.map((node, index) => (
                    <div key={`${node.id}-${index}`} className="flex items-center gap-2">
                      <div className="min-w-[9rem] border-2 border-[#070EF4] px-3 py-2">
                        <p className="meta">{node.kind}</p>
                        <p className="text-sm leading-5">{node.name}</p>
                      </div>
                      {query.edges[index] && <span className="meta max-w-[6rem]">{query.edges[index].source}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
          <section>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="meta">Guard receipts</p>
                <p className="mt-2 text-sm leading-6">
                  {rollbackTotal === 0
                    ? "The guard accepted every refit in this view."
                    : `${rollbackTotal} rollbacks. Each receipt keeps the score before and after the proposal.`}
                </p>
              </div>
              <select aria-label="Seed filter" className="border-2 border-[#070EF4] bg-[#F0F2F1] px-2 py-1 text-sm" value={seedFilter} onChange={(event) => setSeedFilter(event.target.value)}>
                <option value="all">All seeds</option>
                {(view.config?.seeds || results.config.seeds).map((seed) => (
                  <option key={seed} value={String(seed)}>Seed {seed}</option>
                ))}
              </select>
            </div>
            <ol className="mt-4 max-h-[28rem] space-y-2 overflow-y-auto">
              {policies.slice(0, 24).map((version) => (
                <li key={`${version.version}-${version.seed}-${version.iteration}`} className="border-t-2 border-[#070EF4] py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm">v{version.version} · iter {version.iteration} · seed {version.seed}</p>
                    <p className="meta">{version.rolled_back ? "Rolled back" : "Accepted"}</p>
                  </div>
                  <p className="mt-1 text-xs leading-5">
                    {version.guard_before == null ? "" : `guard ${pct(version.guard_before)} → ${pct(version.guard_after)}`}
                    {version.heldout_before == null ? "" : ` · held-out ${pct(version.heldout_before)} → ${pct(version.heldout_after)}`}
                    {version.reason ? ` · ${version.reason}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <hr className="rule mt-10" />
        <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
          <p className="meta">Search latency · n={load.n}</p>
          <button type="button" onClick={remeasure} disabled={liveBusy} className="sq">
            {liveBusy ? "Measuring" : "Measure again"}
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {[
            ["p50", load.p50_ms],
            ["p95", load.p95_ms],
            ["p99", load.p99_ms],
          ].map(([label, value]) => (
            <div key={label} className="tile">
              <p className="display display-black text-4xl">{msLabel(value)}</p>
              <p className="meta">{label}</p>
            </div>
          ))}
        </div>

        <hr className="rule mt-10" />
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pb-2">
          <p className="meta">Source: Zenodo 16440960 · OSV · NVD</p>
          <p className="meta">© DreamGraph</p>
        </div>
      </div>
    </div>
  );
}
