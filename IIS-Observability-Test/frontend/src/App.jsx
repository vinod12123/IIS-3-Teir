//import { useCallback, useEffect, useRef, useState } from 'react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
const scenarios = [
  { id: 'healthy', tier: 'API', title: 'Healthy request', detail: 'Normal API response and IIS access log', expected: '200' },
  { id: 'api-error', tier: 'API', title: 'Server error', detail: 'Deliberate HTTP 500', expected: '500' },
  { id: 'api-exception', tier: 'API', title: 'Unhandled exception', detail: 'Real Python exception, returned as 500', expected: '500' },
  { id: 'slow-api', tier: 'API', title: 'Slow API', detail: 'Two-second response latency', expected: '200 · 2s' },
  { id: 'upstream-unavailable', tier: 'API', title: 'Upstream unavailable', detail: 'Simulated dependency failure', expected: '503' },
  { id: 'db-read', tier: 'DATABASE', title: 'Read database', detail: 'Real PostgreSQL count query', expected: '200' },
  { id: 'db-write', tier: 'DATABASE', title: 'Write database', detail: 'Insert one test event', expected: '201' },
  { id: 'slow-db', tier: 'DATABASE', title: 'Slow database query', detail: 'Bounded two-second PostgreSQL query', expected: '200 · 2s' },
  { id: 'db-error', tier: 'DATABASE', title: 'Database query error', detail: 'Real PostgreSQL missing-table error', expected: '500' },
];

const apiUrl = (path) => new URL(`api/${path}`, document.baseURI);
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export default function App() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [activity, setActivity] = useState([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const cancelRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(apiUrl('health'), { cache: 'no-store' });
      setHealth(response.ok ? await response.json() : { api: 'unavailable', database: 'unknown' });
    } catch {
      setHealth({ api: 'unavailable', database: 'unknown' });
    }
    try {
      const response = await fetch(apiUrl('events'), { cache: 'no-store' });
      if (response.ok) setEvents((await response.json()).events);
    } catch {
      // The database panel remains at its last known state when the API is offline.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function run(id) {
    const started = performance.now();
    try {
      const response = await fetch(apiUrl(`scenarios/${id}`), { method: 'POST', cache: 'no-store' });
      const body = await response.json().catch(() => ({}));
      const entry = { at: new Date().toLocaleTimeString(), scenario: id, status: response.status, ms: Math.round(performance.now() - started), message: body.message || '', requestId: response.headers.get('X-Test-Request-Id') || '' };
      setActivity((old) => [entry, ...old].slice(0, 50));
      if (id.startsWith('db-') && response.ok) void refresh();
      return entry;
    } catch (error) {
      const entry = { at: new Date().toLocaleTimeString(), scenario: id, status: 'network error', ms: Math.round(performance.now() - started), message: String(error), requestId: '' };
      setActivity((old) => [entry, ...old].slice(0, 50));
      return entry;
    }
  }

  async function runSeries(id, total, pauseMs) {
    if (busy) return;
    cancelRef.current = false;
    setBusy(true);
    try {
      for (let index = 1; index <= total && !cancelRef.current; index++) {
        await run(id);
        setProgress(`${id}: ${index}/${total} requests sent`);
        if (index < total && !cancelRef.current) await delay(pauseMs);
      }
      if (cancelRef.current) setProgress(`${id}: stopped`);
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  return (
    <main>
      <header>
        <span className="eyebrow">CLOUDSCORE · IIS TEST LAB</span>
        <h1>Three-tier observability test</h1>
        <p>React in IIS → Python API → PostgreSQL. Each button sends a real request and shows its result.</p>
      </header>

      <section className="status-grid" aria-label="Tier health">
        <div className="status-card"><span>FRONTEND</span><strong className="good">Running</strong><small>React page served by IIS</small></div>
        <div className="status-card"><span>API</span><strong className={health?.api === 'ok' ? 'good' : 'bad'}>{health?.api || 'Checking…'}</strong><small>FastAPI behind IIS</small></div>
        <div className="status-card"><span>DATABASE</span><strong className={health?.database === 'ok' ? 'good' : 'bad'}>{health?.database || 'Checking…'}</strong><small>PostgreSQL · {health?.eventCount ?? '—'} test events</small></div>
      </section>

      <section className="panel">
        <div className="section-head"><div><span className="eyebrow">01 · CONTROLLED RUNS</span><h2>Test an incident path</h2></div><button className="secondary" onClick={() => void refresh()}>Refresh health</button></div>
        <p className="muted">Run a healthy baseline first. Error bursts are limited to eight requests. ASTRA still needs IIS/API log collection, an enabled critical monitor, and automatic incident opening.</p>
        <div className="action-row">
          <button disabled={busy} onClick={() => void runSeries('healthy', 30, 1000)}>30 healthy requests</button>
          <button className="danger" disabled={busy} onClick={() => void runSeries('api-error', 8, 2000)}>8 API errors</button>
          <button className="danger" disabled={busy || health?.database !== 'ok'} onClick={() => void runSeries('db-error', 8, 2000)}>8 database errors</button>
          <button className="secondary" disabled={!busy} onClick={() => { cancelRef.current = true; }}>Stop run</button>
        </div>
        <div className="progress" role="status">{progress || 'No batch running'}</div>
      </section>

      <section className="panel">
        <div className="section-head"><div><span className="eyebrow">02 · SINGLE REQUESTS</span><h2>Exercise each tier</h2></div></div>
        <div className="scenario-grid">
          {scenarios.map((item) => (
            <article className="scenario" key={item.id}>
              <div className="scenario-top"><span className="eyebrow">{item.tier}</span><span className="expected">HTTP {item.expected}</span></div>
              <h3>{item.title}</h3><p>{item.detail}</p>
              <button className={item.expected.startsWith('5') ? 'danger' : ''} disabled={busy} onClick={() => void run(item.id)}>Run scenario</button>
            </article>
          ))}
        </div>
      </section>

      <div className="bottom-grid">
        <section className="panel"><span className="eyebrow">03 · BROWSER RESULTS</span><h2>Recent requests</h2><div className="results">{activity.length ? activity.map((entry, index) => <div className="result" key={`${entry.at}-${index}`}><span>{entry.at}</span><strong className={Number(entry.status) >= 500 ? 'bad' : 'good'}>{entry.status}</strong><div><b>{entry.scenario}</b><small>{entry.message}</small></div><span>{entry.ms} ms</span></div>) : <p className="muted">Run a scenario to see results.</p>}</div></section>
        <section className="panel"><span className="eyebrow">04 · DATABASE RECORDS</span><h2>Recent writes</h2><div className="results">{events.length ? events.map((event) => <div className="result" key={event.id}><span>#{event.id}</span><div><b>{event.scenario}</b><small>{new Date(event.created_at).toLocaleString()}</small></div></div>) : <p className="muted">Run “Write database” to create a record.</p>}</div></section>
      </div>
      <footer>Test machine only. This page cannot start or stop Windows services or the database.</footer>
    </main>
  );
}
