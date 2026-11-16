import { StrictMode, lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Landing from "./Landing.jsx";
import "./index.css";

const Explorer = lazy(() => import("./explorer/Explorer.jsx"));

function usePath() {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const sync = () => setPath(window.location.pathname);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  return path;
}

function Root() {
  const path = usePath();
  if (path === "/graph" || path.startsWith("/graph/")) {
    return (
      <Suspense fallback={<div className="frame wrap" style={{ padding: 24 }}>Loading the graph…</div>}>
        <Explorer onClose={() => { window.location.assign("/dashboard"); }} />
      </Suspense>
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
