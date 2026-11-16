import { useEffect, useState } from "react";

export default function useResults() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [waking, setWaking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer;
    async function load() {
      try {
        const response = await fetch("/api/results");
        if (!response.ok) {
          if (response.status >= 500) throw new Error("waking");
          const body = await response.json().catch(() => ({}));
          if (!cancelled) {
            setError(body.detail || `Results request failed (${response.status})`);
            setWaking(false);
          }
          return;
        }
        const body = await response.json();
        if (!cancelled) {
          setResults(body);
          setError("");
          setWaking(false);
        }
      } catch {
        if (!cancelled) {
          setWaking(true);
          timer = window.setTimeout(load, 3000);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  return { results, error, waking };
}
