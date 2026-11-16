import { Component, StrictMode, Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Landing from "./Landing.jsx";
import { navigate } from "./route.js";
import "./index.css";

function lazyWithRetry(importer) {
  return lazy(() =>
    importer().catch((error) => {
      const key = "dg-chunk-retry";
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, "1");
        window.location.reload();
        return new Promise(() => {});
      }
      sessionStorage.removeItem(key);
      throw error;
    }),
  );
}

const Explorer = lazyWithRetry(() => import("./explorer/Explorer.jsx"));

function usePath() {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const sync = () => setPath(window.location.pathname);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  return path;
}

function GraphLoading() {
  const [progress, setProgress] = useState(8);
  useEffect(() => {
    const timer = setInterval(() => {
      setProgress((value) => (value >= 90 ? value : value + Math.max(1, (90 - value) / 8)));
    }, 200);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="frame" style={{ margin: 16, padding: 28 }}>
      <p className="meta">DreamGraph</p>
      <h1 className="display" style={{ fontSize: 64, marginTop: 16 }}>Loading the 3D graph</h1>
      <p style={{ maxWidth: 520, marginTop: 12 }}>The graph bundle is about 1.4 MB. On the free host the first download can take a moment.</p>
      <div className="bar-track" style={{ marginTop: 28, maxWidth: 480 }} aria-hidden="true">
        <div className="bar-fill" style={{ width: `${Math.round(progress)}%` }} />
      </div>
      <p className="meta" style={{ marginTop: 10 }}>{Math.round(progress)}%</p>
    </div>
  );
}

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="frame" style={{ margin: 16, padding: 28 }}>
        <p className="meta">Graph error</p>
        <h1 className="display" style={{ fontSize: 56, marginTop: 12 }}>The 3D graph failed to start</h1>
        <pre className="nb" style={{ marginTop: 20, padding: 16, whiteSpace: "pre-wrap", fontFamily: "IBM Plex Mono, monospace", fontSize: 13 }}>
          {this.state.error?.message || String(this.state.error)}
        </pre>
        <p style={{ marginTop: 16 }}>
          <a className="sq sq-invert" href="/graph">Reload the graph</a>
          <a className="sq" href="/dashboard" style={{ marginLeft: 12 }}>See the live dashboard</a>
        </p>
      </div>
    );
  }
}

function Root() {
  const path = usePath();
  if (path === "/graph" || path.startsWith("/graph/")) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<GraphLoading />}>
          <Explorer onClose={() => navigate("/dashboard")} />
        </Suspense>
      </ErrorBoundary>
    );
  }
  if (path === "/dashboard" || path.startsWith("/dashboard/")) return <App />;
  return <Landing />;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
