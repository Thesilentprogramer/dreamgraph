const BLUE = "#070EF4";

export const LABELS = {
  dreamgraph: "DreamGraph",
  dict_learner: "Dict learner",
  unweighted: "Unweighted",
  hand_set: "Hand-set costs",
  one_shot: "One-shot fit",
  greedy: "Greedy online",
  bm25: "BM25 labels",
  frozen_at_3: "Frozen after 3",
  one_hop: "1-hop lookup",
  naive: "Naive, no guard",
  majority: "Majority vote",
  nvd_only: "NVD only",
  ghsa_only: "GHSA only",
  conditional_k1: "Conditional, k=1",
  topk_open: "Top-5, no margin",
  per_feed: "Per-feed cost",
};

const ORDER = [
  "unweighted",
  "bm25",
  "hand_set",
  "one_shot",
  "one_hop",
  "naive",
  "majority",
  "nvd_only",
  "ghsa_only",
  "per_feed",
  "topk_open",
  "conditional_k1",
  "greedy",
  "frozen_at_3",
  "dict_learner",
  "dreamgraph",
];

const DASHED = new Set([
  "dict_learner",
  "one_shot",
  "greedy",
  "one_hop",
  "naive",
  "nvd_only",
  "majority",
  "per_feed",
  "topk_open",
  "unweighted",
  "hand_set",
  "bm25",
  "ghsa_only",
  "conditional_k1",
  "frozen_at_3",
]);

export default function Chart({ series, driftIter, markers, hidden, onToggle, order }) {
  const width = 860;
  const height = 340;
  const pad = { l: 48, r: 16, t: 22, b: 32 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const methods = (order || ORDER).filter((method) => series?.[method]?.accuracy);
  const anchor = series?.dreamgraph?.accuracy ? "dreamgraph" : methods[0];
  const steps = anchor ? series[anchor].accuracy.length : 0;
  const x = (iteration) => pad.l + (steps <= 1 ? innerW / 2 : ((iteration - 1) / (steps - 1)) * innerW);
  const y = (value) => pad.t + (1 - value) * innerH;
  const pins = markers || (driftIter ? [{ iter: driftIter, label: "Drift" }] : []);

  if (!steps) {
    return <p className="text-sm">No series in this export.</p>;
  }

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Held-out accuracy by iteration">
        {[0.4, 0.6, 0.8, 1].map((tick) => (
          <g key={tick}>
            <line x1={pad.l} x2={width - pad.r} y1={y(tick)} y2={y(tick)} stroke={BLUE} strokeWidth="1" opacity="0.35" />
            <text x={pad.l - 8} y={y(tick) + 4} textAnchor="end" fill={BLUE} fontSize="11" fontFamily="IBM Plex Mono, monospace">
              {Math.round(tick * 100)}
            </text>
          </g>
        ))}
        {pins.map((pin) => (
          <g key={`${pin.label}-${pin.iter}`}>
            <rect x={x(pin.iter) - 6} y={pad.t} width="12" height={innerH} fill={BLUE} opacity="0.12" />
            <text x={x(pin.iter) + 10} y={pad.t + 12} fill={BLUE} fontSize="11" fontFamily="IBM Plex Mono, monospace">
              {pin.label}
            </text>
          </g>
        ))}
        {methods.filter((method) => !hidden?.[method]).map((method) => {
          const values = series[method].accuracy;
          const points = values.map((value, index) => `${x(index + 1)},${y(value)}`).join(" ");
          return (
            <g key={method}>
              <polyline
                points={points}
                fill="none"
                stroke={BLUE}
                strokeWidth={method === "dreamgraph" ? 2.5 : 1.25}
                strokeDasharray={method === "dreamgraph" ? undefined : DASHED.has(method) ? "6 4" : undefined}
                strokeOpacity={method === "dreamgraph" ? 1 : 0.55}
              />
              {method === "dreamgraph" &&
                values.map((value, index) => (
                  <rect key={index} x={x(index + 1) - 3.5} y={y(value) - 3.5} width="7" height="7" fill={BLUE} />
                ))}
            </g>
          );
        })}
        {Array.from({ length: steps }, (_, index) => (
          <text key={index} x={x(index + 1)} y={height - 8} textAnchor="middle" fill={BLUE} fontSize="11" fontFamily="IBM Plex Mono, monospace">
            {index + 1}
          </text>
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap gap-2">
        {methods.map((method) => {
          const off = hidden?.[method];
          return (
            <button
              key={method}
              type="button"
              aria-pressed={!off}
              onClick={() => onToggle(method)}
              className={off ? "sq" : "sq sq-invert"}
              style={{ opacity: off ? 0.45 : 1 }}
            >
              <span className="meta">{LABELS[method] || method}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export { ORDER };
