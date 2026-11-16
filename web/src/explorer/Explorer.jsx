import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";

const BLUE = "#070EF4";

const TYPE_LABEL = {
  feed: "Feed",
  cve: "CVE",
  claim: "Claim",
  project: "Project",
  version: "Version",
  verdict: "Verdict",
  group: "Group",
  company: "Company",
  person: "Person",
};

function hasWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function paint() {
  return BLUE;
}

function radiusOf(node, costs) {
  if (node.type === "feed") {
    const cost = costs[node.name] ?? node.cost ?? 1;
    return 1.35 + 1.7 / (1 + cost);
  }
  if (node.type === "group") return 1.15;
  if (node.type === "project" || node.type === "cve") return 1.05;
  if (node.type === "verdict") return 0.9;
  return 0.62;
}

function endId(value) {
  return value?.id || value;
}

function neighborIdsOf(focusId, links) {
  const ids = new Set();
  if (!focusId) return ids;
  for (const link of links) {
    const source = endId(link.source);
    const target = endId(link.target);
    if (source === focusId) ids.add(target);
    else if (target === focusId) ids.add(source);
  }
  return ids;
}

const labelElements = new Map();

function makeLabel(node) {
  let el = labelElements.get(node.id);
  if (!el) {
    el = document.createElement("div");
    el.textContent = node.name;
    el.style.color = BLUE;
    el.style.fontFamily = "IBM Plex Mono, ui-monospace, monospace";
    el.style.fontSize = "11px";
    el.style.fontWeight = "500";
    el.style.letterSpacing = "0.08em";
    el.style.textTransform = "uppercase";
    el.style.pointerEvents = "none";
    el.style.whiteSpace = "nowrap";
    el.dataset.id = node.id;
    labelElements.set(node.id, el);
  }
  node.__label = el;
  const object = new CSS2DObject(el);
  object.visible = false;
  object.position.set(0, radiusOf(node, {}) + 1.4, 0);
  node.__css = object;
  return object;
}

function sphereFor(node, costs) {
  const group = new THREE.Group();
  const radius = radiusOf(node, costs);
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 20, 20),
    new THREE.MeshBasicMaterial({ color: BLUE, transparent: true, opacity: 0.2 }),
  );
  const wire = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.18, 14, 14),
    new THREE.MeshBasicMaterial({ color: BLUE, wireframe: true }),
  );
  node.__mesh = mesh;
  node.__wire = wire;
  group.add(mesh);
  group.add(wire);
  group.add(makeLabel(node));
  return group;
}

function parseAsk(text) {
  const match = text.match(/is\s+(.+?)\s+affected\s+by\s+(CVE-\d{4}-\d+)/i);
  if (!match) return null;
  return { subject: match[1].trim().toLowerCase(), cve: match[2].toUpperCase() };
}

export default function Explorer({ onClose }) {
  const fgRef = useRef(null);
  const stars = useRef(null);
  const extraRenderers = useMemo(() => [new CSS2DRenderer()], []);
  const costsRef = useRef({});
  const nodeObject = useCallback((node) => sphereFor(node, costsRef.current), []);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [webgl] = useState(hasWebGL);
  const [hidden, setHidden] = useState({ company: true, person: true });
  const [iteration, setIteration] = useState(8);
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [panel, setPanel] = useState(true);
  const [tab, setTab] = useState("overview");
  const [query, setQuery] = useState("is linux v2.6.16 affected by CVE-2022-3628?");
  const [search, setSearch] = useState("");
  const [ask, setAsk] = useState(null);
  const [askError, setAskError] = useState("");
  const [pulse, setPulse] = useState(() => new Set());
  const [framed, setFramed] = useState(0);
  const [modal, setModal] = useState(null);
  const [extraNodes, setExtraNodes] = useState([]);
  const [extraLinks, setExtraLinks] = useState([]);
  const [opened, setOpened] = useState(() => new Set());

  useEffect(() => {
    let cancelled = false;
    fetch("/api/explorer")
      .then(async (response) => {
        if (!response.ok) throw new Error("Graph export is missing");
        return response.json();
      })
      .then((body) => {
        if (!cancelled) {
          setGraph(body);
          setIteration(body.iterations?.at(-1)?.iteration || 8);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load the graph");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const costs = useMemo(() => {
    const frame = graph?.iterations?.find((item) => item.iteration === Number(iteration));
    return frame?.costs || {};
  }, [graph, iteration]);
  costsRef.current = costs;

  const visible = useMemo(() => {
    if (!graph) return { nodes: [], links: [] };
    const dropped = new Set(opened);
    const nodes = [...graph.nodes.filter((node) => !dropped.has(node.id)), ...extraNodes].filter(
      (node) => !hidden[node.type],
    );
    const ids = new Set(nodes.map((node) => node.id));
    const links = [...graph.links, ...extraLinks].filter((link) => {
      const source = link.source.id || link.source;
      const target = link.target.id || link.target;
      return ids.has(source) && ids.has(target);
    });
    return { nodes, links };
  }, [graph, hidden, extraNodes, extraLinks, opened]);

  const focusNeighbors = useMemo(
    () => neighborIdsOf(selected?.id, visible.links),
    [selected, visible.links],
  );

  const sceneGraph = useMemo(() => {
    const nodes = visible.nodes;
    const focusId = selected?.id;
    const links = visible.links.filter((link) => {
      if (!focusId) return false;
      if (pulse.has(link.id)) return true;
      const source = endId(link.source);
      const target = endId(link.target);
      return source === focusId || target === focusId;
    });
    if (focusId) {
      const nearIds = new Set(focusNeighbors);
      for (const link of links) {
        const source = endId(link.source);
        const target = endId(link.target);
        if (source !== focusId) nearIds.add(source);
        if (target !== focusId) nearIds.add(target);
      }
      const near = nodes.filter((node) => nearIds.has(node.id));
      const rest = nodes.filter((node) => node.id !== focusId && !nearIds.has(node.id));
      const pin = (node, x, y, z) => {
        node.fx = x;
        node.fy = y;
        node.fz = z;
        node.x = x;
        node.y = y;
        node.z = z;
      };
      const focus = nodes.find((node) => node.id === focusId);
      if (focus) pin(focus, 0, 0, 0);
      const crowded = near.length > 14;
      near.forEach((node, index) => {
        if (!crowded) {
          const angle = (index / Math.max(near.length, 1)) * Math.PI * 2 - Math.PI / 2;
          const ring = 42;
          pin(node, Math.cos(angle) * ring, Math.sin(angle) * ring * 0.72, Math.sin(angle * 2) * 8);
          return;
        }
        const y = 1 - (index / Math.max(near.length - 1, 1)) * 2;
        const radial = Math.sqrt(Math.max(0, 1 - y * y));
        const theta = Math.PI * (3 - Math.sqrt(5)) * index;
        const radius = 96;
        pin(node, Math.cos(theta) * radial * radius, y * radius * 0.62, Math.sin(theta) * radial * radius);
      });
      rest.forEach((node, index) => {
        const angle = (index / Math.max(rest.length, 1)) * Math.PI * 2;
        const shell = 640 + (index % 8) * 24;
        pin(node, Math.cos(angle) * shell, Math.sin(angle) * shell * 0.22, ((index % 7) - 3) * 40);
      });
    }
    return { nodes, links };
  }, [visible, selected, focusNeighbors, pulse]);

  useEffect(() => {
    if (!graph || selected) return;
    const focal =
      graph.nodes.find((node) => node.id === "version:linux:v2.6.16") ||
      graph.nodes.find((node) => node.type === "version") ||
      graph.nodes.find((node) => node.type === "feed" && node.name === "nvd");
    if (focal) setSelected(focal);
  }, [graph, selected]);

  useEffect(() => {
    if (!selected || !fgRef.current) return;
    const distance = focusNeighbors.size > 14 ? 240 : 118;
    const shift = distance * 0.13;
    fgRef.current.cameraPosition({ x: 6, y: 16, z: distance }, { x: -shift, y: 0, z: 0 }, 700);
    const early = setTimeout(() => setFramed((count) => count + 1), 400);
    const later = setTimeout(() => setFramed((count) => count + 1), 1400);
    return () => {
      clearTimeout(early);
      clearTimeout(later);
    };
  }, [selected, focusNeighbors]);

  useEffect(() => {
    const seenLabels = new Map();
    fgRef.current?.scene?.().traverse((object) => {
      if (!object.isCSS2DObject) return;
      const id = object.element?.dataset?.id;
      if (!id) return;
      const previous = seenLabels.get(id);
      if (previous) previous.removeFromParent();
      seenLabels.set(id, object);
    });
    for (const node of visible.nodes) {
      const mesh = node.__mesh;
      const wire = node.__wire;
      const label = node.__css;
      const isFocus = node.id === selected?.id;
      const isNeighbor = focusNeighbors.has(node.id);
      const isHover = node.id === hovered?.id;
      const near = isFocus || isNeighbor;
      const showLabel = isFocus || isNeighbor || isHover || (node.type === "feed" && near);
      const scale = isFocus ? 7 : isNeighbor ? 2.2 : 0.4;
      if (mesh) {
        mesh.scale.setScalar(scale);
        mesh.material.opacity = isFocus ? 1 : isNeighbor ? 0.45 : 0.1;
        mesh.material.transparent = !isFocus;
        mesh.material.wireframe = false;
      }
      if (wire) {
        wire.scale.setScalar(scale);
        wire.visible = isNeighbor && !isFocus;
      }
      if (label) {
        label.visible = showLabel;
        label.position.y = radiusOf(node, costs) * scale + 1.6;
        if (label.element) label.element.style.fontSize = isFocus ? "13px" : "10px";
      }
    }
  }, [selected, hovered, focusNeighbors, visible.nodes, costs, extraRenderers, framed]);

  useEffect(() => {
    if (!webgl || !fgRef.current || !graph) return undefined;
    const fg = fgRef.current;
    const controls = fg.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.12;
    controls.enableDamping = true;
    const pause = () => {
      controls.autoRotate = false;
    };
    const resume = () => {
      controls.autoRotate = true;
    };
    controls.addEventListener("start", pause);
    controls.addEventListener("end", resume);
    const labelLayer = extraRenderers[0]?.domElement;
    if (labelLayer) {
      labelLayer.style.zIndex = "5";
      labelLayer.style.pointerEvents = "none";
    }
    return () => {
      controls.removeEventListener("start", pause);
      controls.removeEventListener("end", resume);
    };
  }, [webgl, graph]);

  function onNodeClick(node) {
    setSelected(node);
    setPanel(true);
    setTab("overview");
    if (node.type === "group") setModal(node);
  }

  function explode(group) {
    const parent = visible.nodes.find((node) => node.id === group.id) || group;
    const members = (group.members || []).map((member, index) => ({
      ...member,
      x: (parent.x || 0) + Math.cos(index) * 12,
      y: (parent.y || 0) + Math.sin(index) * 12,
      z: parent.z || 0,
    }));
    setExtraNodes((current) => [...current, ...members]);
    setExtraLinks((current) => [...current, ...(group.memberLinks || [])]);
    setOpened((current) => new Set([...current, group.id]));
    setModal(null);
    setSelected(members[0] || null);
    requestAnimationFrame(() => fgRef.current?.d3ReheatSimulation());
  }

  function runSearch(event) {
    event.preventDefault();
    const needle = search.trim().toLowerCase();
    if (!needle) return;
    const node =
      visible.nodes.find((item) => item.type === "feed" && item.name.toLowerCase() === needle) ||
      visible.nodes.find((item) => item.name.toLowerCase() === needle) ||
      visible.nodes.find((item) => item.name.toLowerCase().includes(needle));
    if (!node) {
      setAskError(`No node matches “${search}”.`);
      return;
    }
    setAskError("");
    setSelected(node);
    setPanel(true);
    if (node.type === "group") setModal(node);
  }

  async function askHydra(event) {
    event.preventDefault();
    setAskError("");
    setAsk(null);
    setPulse(new Set());
    const parsed = parseAsk(query);
    if (!parsed) {
      setAskError("Ask in the form: is linux v2.6.16 affected by CVE-2022-3628?");
      return;
    }
    const match = (graph.queries || []).find(
      (item) => item.cveId.toLowerCase() === `cve:${parsed.cve.toLowerCase()}` && item.text.toLowerCase().includes(parsed.subject),
    );
    if (!match) {
      setAskError("That tag is not in the loaded sample. Try one of the example questions.");
      return;
    }
    const steps = [
      `Parsed ${parsed.subject} and ${parsed.cve}.`,
      `Matched held-out question ${match.rel}.`,
    ];
    setAsk({ steps, pending: true });
    try {
      const response = await fetch(`/api/query?rel=${match.rel}&mode=dreamgraph&dataset=vuln`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "HydraDB query failed");
      const feed = body.edges?.[0]?.source;
      const ids = [match.projectId, match.cveId, match.versionId, feed ? `feed:${feed}` : null, feed ? `claim:${feed}:${parsed.cve}:${match.label.split(" ")[1]}` : null, `verdict:${body.gold_name}`].filter(Boolean);
      const idSet = new Set(ids);
      const lit = new Set(
        visible.links
          .filter((link) => idSet.has(link.source.id || link.source) && idSet.has(link.target.id || link.target))
          .map((link) => link.id),
      );
      setPulse(lit);
      const node = visible.nodes.find((item) => item.id === match.versionId);
      if (node) setSelected(node);
      setAsk({
        pending: false,
        steps: [
          ...steps,
          `Ran weighted algo.SSpaths over ${body.path?.length || 0} nodes.`,
          `Winning path weight ${body.weight} via ${feed || "the cheapest feed"}. ${body.correct ? "Matches the Zenodo label." : "Does not match the Zenodo label."}`,
        ],
        path: body.path,
        correct: body.correct,
      });
    } catch (err) {
      setAsk(null);
      setAskError(err.message || "HydraDB query failed");
    }
  }

  const frame = graph?.iterations?.find((item) => item.iteration === Number(iteration));
  const neighbors = selected
    ? visible.links
        .filter((link) => (link.source.id || link.source) === selected.id || (link.target.id || link.target) === selected.id)
        .map((link) => {
          const otherId = (link.source.id || link.source) === selected.id ? link.target.id || link.target : link.source.id || link.source;
          return visible.nodes.find((node) => node.id === otherId);
        })
        .filter(Boolean)
    : [];

  return (
    <div className="fixed inset-0 z-40 bg-[#F0F2F1] text-[#070EF4]">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-3 p-3">
        <button type="button" onClick={onClose} className="pointer-events-auto border-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-1.5 text-xs uppercase tracking-[0.14em]">
          Back to dashboard
        </button>
        <div className="pointer-events-auto flex flex-col items-end gap-2">
          <form onSubmit={runSearch} className="flex gap-2">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search CVE, feed, version"
              aria-label="Search the graph"
              className="w-56 border-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-1.5 text-xs uppercase outline-none"
            />
          </form>
          {graph && (
            <label className="meta flex items-center gap-2 border-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-1.5">
              Iteration {iteration}
              {frame?.drift ? " · newer feeds" : ""}
              {frame?.rollback ? " · guard rollback" : ""}
              <input
                className="dg-range"
                type="range"
                min={graph.iterations[0].iteration}
                max={graph.iterations.at(-1).iteration}
                value={iteration}
                onChange={(event) => setIteration(Number(event.target.value))}
                aria-label="Scrub learned costs by iteration"
              />
            </label>
          )}
        </div>
      </div>

      {panel && (
        <aside className="absolute bottom-16 left-3 top-16 z-20 flex w-[22rem] max-w-[calc(100%-1.5rem)] flex-col border-2 border-[#070EF4] bg-[#F0F2F1] p-4">
          <div className="flex items-start justify-between gap-2">
            <p className="meta">
              {selected ? `${TYPE_LABEL[selected.type] || selected.type} / ${selected.cluster || "vuln"}` : "Graph"}
            </p>
            <button type="button" onClick={() => setPanel(false)} className="meta">
              Hide
            </button>
          </div>
          <h2 className="display display-black mt-1 text-4xl">{selected?.name || "Vulnerability graph"}</h2>
          <div className="mt-3 flex gap-2 text-xs">
            {["overview", "ask"].map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setTab(name)}
                className="px-3 py-1 uppercase tracking-[0.12em]"
                style={
                  tab === name
                    ? { background: "#070EF4", color: "#F4F5FA", border: "2px solid #070EF4" }
                    : { background: "#F0F2F1", color: "#070EF4", border: "2px solid #070EF4" }
                }
              >
                {name === "overview" ? "Overview" : "Ask HydraDB"}
              </button>
            ))}
          </div>
          {tab === "overview" ? (
            <div className="mt-4 space-y-3 overflow-y-auto text-sm">
              {selected?.type === "feed" || selected?.cost != null ? (
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <div><dt className="meta">Learned cost</dt><dd className="font-mono text-base">{(costs[selected?.name] ?? selected?.cost ?? "—").toString().slice(0, 6)}</dd></div>
                  <div><dt className="meta">Measured accuracy</dt><dd className="font-mono text-base">{selected?.accuracy == null ? "—" : `${(selected.accuracy * 100).toFixed(1)}%`}</dd></div>
                  <div><dt className="meta">Judgments</dt><dd className="font-mono text-base">{selected?.n ?? "—"}</dd></div>
                  <div><dt className="meta">Drift delta</dt><dd className="font-mono text-base">{selected?.drift == null ? "—" : selected.drift.toFixed(3)}</dd></div>
                </dl>
              ) : (
                <p className="text-xs leading-5">
                  {graph ? `${graph.node_count} nodes in this sample, capped at ${graph.cap}. Costs follow the published policy versions.` : "Loading the sample."}
                </p>
              )}
              {selected?.gold && <p className="text-xs">Zenodo label: {selected.gold}</p>}
              {selected?.vote && <p className="text-xs">This claim votes {selected.vote}.</p>}
              <div>
                <p className="meta">Neighbors</p>
                <ul className="mt-1 space-y-1">
                  {neighbors.map((node) => (
                    <li key={node.id}>
                      <button type="button" className="text-left text-xs uppercase" onClick={() => onNodeClick(node)}>
                        {TYPE_LABEL[node.type]} · {node.name}
                      </button>
                    </li>
                  ))}
                  {selected && neighbors.length === 0 && <li className="text-xs">No neighbors in the current filter.</li>}
                </ul>
              </div>
            </div>
          ) : (
            <form onSubmit={askHydra} className="mt-4 flex min-h-0 flex-1 flex-col gap-2">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Ask HydraDB"
                className="h-24 border-2 border-[#070EF4] bg-[#F0F2F1] p-2 text-sm outline-none"
              />
              <button type="submit" className="bg-[#070EF4] px-3 py-2 text-xs font-medium uppercase tracking-[0.14em] text-[#F4F5FA]">
                Run weighted path
              </button>
              {askError && <p className="text-xs">{askError}</p>}
              {ask && (
                <ol className="space-y-1 overflow-y-auto text-xs leading-5">
                  {ask.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              )}
            </form>
          )}
        </aside>
      )}
      {!panel && (
        <button type="button" onClick={() => setPanel(true)} className="absolute left-3 top-16 z-20 border-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-1.5 text-xs uppercase">
          Show context
        </button>
      )}

      <div className="absolute inset-x-0 bottom-0 z-20 flex flex-wrap items-center gap-2 border-t-2 border-[#070EF4] bg-[#F0F2F1] px-3 py-2 text-[11px]">
        {(graph?.types || Object.keys(TYPE_LABEL)).map((type) => (
          <button
            key={type}
            type="button"
            aria-pressed={!hidden[type]}
            onClick={() => setHidden((current) => ({ ...current, [type]: !current[type] }))}
            className="inline-flex items-center gap-1.5 border-2 border-[#070EF4] px-2 py-1 uppercase"
            style={{ opacity: hidden[type] ? 0.35 : 1, background: hidden[type] ? "transparent" : "#070EF4", color: hidden[type] ? "#070EF4" : "#F4F5FA" }}
          >
            <span className="inline-block h-2 w-2" style={{ background: hidden[type] ? "#070EF4" : "#F4F5FA" }} />
            {TYPE_LABEL[type] || type}
          </button>
        ))}
      </div>

      {error && <p className="absolute left-1/2 top-1/2 -translate-x-1/2 text-sm text-[#f07178]">{error}</p>}
      {!webgl && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-8 text-center">
          <div className="max-w-md rounded-2xl border border-white/10 bg-black/80 p-6">
            <p className="font-serif text-2xl">WebGL is not available</p>
            <p className="mt-2 text-sm text-white/70">The 3D explorer needs a WebGL context. The rest of the dashboard still works, and the graph JSON is served at /api/explorer.</p>
          </div>
        </div>
      )}
      {webgl && graph && (
        <ForceGraph3D
          ref={fgRef}
          graphData={sceneGraph}
          extraRenderers={extraRenderers}
          backgroundColor="#F0F2F1"
          showNavInfo={false}
          nodeRelSize={1}
          nodeVal={(node) => radiusOf(node, costs)}
          nodeOpacity={0.95}
          nodeThreeObject={nodeObject}
          nodeThreeObjectExtend={false}
          linkColor={(link) => {
            const id = link.target.id || link.target;
            const node = visible.nodes.find((item) => item.id === id);
            return node ? paint(node, costs) : "#94a3b8";
          }}
          linkOpacity={(link) => {
            if (pulse.has(link.id)) return 0.9;
            const source = endId(link.source);
            const target = endId(link.target);
            const near = source === selected?.id || target === selected?.id;
            if (!near) return 0.035;
            const trust = 1 / (1 + (costs[link.feed] ?? 1));
            return 0.15 + 0.2 * trust;
          }}
          linkWidth={(link) => {
            if (pulse.has(link.id)) return 0.45;
            const trust = 1 / (1 + (costs[link.feed] ?? 1));
            return 0.06 + 0.28 * trust;
          }}
          onNodeHover={setHovered}
          linkDirectionalParticles={(link) => (pulse.has(link.id) ? 4 : 0)}
          linkDirectionalParticleWidth={1.5}
          linkDirectionalParticleSpeed={0.01}
          linkDirectionalParticleColor={() => "#070EF4"}
          onNodeClick={onNodeClick}
          cooldownTicks={0}
        />
      )}

      {modal && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#F0F2F1]/80 p-4" role="dialog" aria-modal="true">
          <div className="max-h-[80vh] w-full max-w-lg overflow-hidden border-2 border-[#070EF4] bg-[#F0F2F1] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="meta">{modal.cve}</p>
                <h3 className="display display-black text-4xl">{modal.name}</h3>
              </div>
              <button type="button" onClick={() => setModal(null)} className="meta">
                Close
              </button>
            </div>
            <div className="mt-3 max-h-72 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr><th className="py-1">Feed</th><th>Version</th><th>Vote</th></tr>
                </thead>
                <tbody>
                  {(modal.members || []).map((member) => (
                    <tr key={member.id} className="border-t-2 border-[#070EF4]">
                      <td className="py-1.5">{member.feed}</td>
                      <td>{member.version}</td>
                      <td>{member.vote}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={() => explode(modal)} className="mt-4 bg-[#070EF4] px-3 py-2 text-xs font-medium uppercase tracking-[0.14em] text-[#F4F5FA]">
              Show on graph instead
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
