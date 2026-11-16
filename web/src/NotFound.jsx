export default function NotFound() {
  return (
    <main className="frame not-found">
      <p className="meta">DreamGraph · 404</p>
      <div>
        <p className="not-found-number" aria-hidden="true">404</p>
        <h1 className="display">No path to this page</h1>
        <p>The address has no route in this graph. Start again from the project overview or open the dashboard.</p>
        <div className="not-found-actions">
          <a className="sq sq-invert" href="/">Back to DreamGraph</a>
          <a className="sq" href="/dashboard">Open dashboard</a>
        </div>
      </div>
      <p className="meta">The graph is intact. This link is missing.</p>
    </main>
  );
}
