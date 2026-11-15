const COLORS = {
  dreamgraph: "#3cbfa8",
  dict_learner: "#9adfd2",
  unweighted: "#c5cdd8",
  hand_set: "#e2a15a",
  one_shot: "#d38bdc",
  greedy: "#7aa2f7",
  bm25: "#d7c07a",
  frozen_at_3: "#e15d5d",
};

export const LABELS = {
  dreamgraph: "DreamGraph",
  dict_learner: "Dict learner",
  unweighted: "Unweighted",
  hand_set: "Hand-set costs",
  one_shot: "One-shot fit",
  greedy: "Greedy online",
  bm25: "BM25 labels",
  frozen_at_3: "Frozen after 3",
};

const ORDER = [
  "unweighted",
  "bm25",
  "hand_set",
  "one_shot",
  "greedy",
  "frozen_at_3",
  "dict_learner",
  "dreamgraph",
];

const BANDS = new Set(["dreamgraph", "unweighted", "hand_set", "frozen_at_3"]);

export default function Chart({ series, driftIter, hidden, onToggle }) {
  const width = 800;
  const height = 360;
  const pad = { l: 48, r: 16, t: 18, b: 36 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const steps = series.dreamgraph.accuracy.length;
  const x = (iteration) => pad.l + ((iteration - 1) / (steps - 1)) * innerW;
  const y = (value) => pad.t + (1 - value) * innerH;

  const bandPath = (method) => {
    const low = series[method].ci_low;
    const high = series[method].ci_high;
    const forward = high.map((value, index) => `${index === 0 ? "M" : "L"}${x(index + 1)},${y(value)}`);
    const back = [...low]
      .reverse()
      .map((value, index) => `L${x(steps - index)},${y(value)}`);
    return `${forward.join("")}${back.join("")}Z`;
  };

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Held-out accuracy by iteration">
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line
              x1={pad.l}
              x2={width - pad.r}
              y1={y(tick)}
              y2={y(tick)}
              stroke="#2a3140"
              strokeWidth="1"
            />
            <text x={pad.l - 8} y={y(tick) + 4} textAnchor="end" fill="#8b97a8" fontSize="11" fontFamily="IBM Plex Mono, monospace">
              {Math.round(tick * 100)}
            </text>
          </g>
        ))}
        <line
          x1={x(driftIter)}
          x2={x(driftIter)}
          y1={pad.t}
          y2={height - pad.b}
          stroke="#e2a15a"
          strokeDasharray="4 4"
          strokeWidth="1.5"
        />
        <text x={x(driftIter) + 6} y={pad.t + 12} fill="#e2a15a" fontSize="11" fontFamily="IBM Plex Sans, sans-serif">
          Drift
        </text>
        {ORDER.filter((method) => !hidden[method] && BANDS.has(method)).map((method) => (
          <path key={`${method}-band`} d={bandPath(method)} fill={COLORS[method]} opacity="0.13" />
        ))}
        {ORDER.filter((method) => !hidden[method]).map((method) => {
          const points = series[method].accuracy
            .map((value, index) => `${x(index + 1)},${y(value)}`)
            .join(" ");
          const dashed = method === "dict_learner" || method === "one_shot" || method === "greedy";
          return (
            <polyline
              key={method}
              points={points}
              fill="none"
              stroke={COLORS[method]}
              strokeWidth={method === "dreamgraph" ? 2.6 : 1.6}
              strokeDasharray={dashed ? "5 4" : undefined}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}
        {Array.from({ length: steps }, (_, index) => (
          <text
            key={index}
            x={x(index + 1)}
            y={height - 12}
            textAnchor="middle"
            fill="#8b97a8"
            fontSize="11"
            fontFamily="IBM Plex Mono, monospace"
          >
            {index + 1}
          </text>
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap gap-2">
        {ORDER.map((method) => {
          const off = hidden[method];
          return (
            <button
              key={method}
              type="button"
              aria-pressed={!off}
              onClick={() => onToggle(method)}
              className="inline-flex items-center gap-2 rounded-full border border-line px-2.5 py-1 text-xs text-muted hover:text-ink"
              style={{ opacity: off ? 0.4 : 1 }}
            >
              <span className="inline-block h-2 w-4 rounded-sm" style={{ background: COLORS[method] }} />
              {LABELS[method]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export { COLORS, ORDER };
