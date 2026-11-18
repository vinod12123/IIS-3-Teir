import React, { useCallback, useEffect, useRef, useState } from 'react';

const api = (path) => new URL(`api/${path}`, document.baseURI);
const controller = (path) => `http://127.0.0.1:8010/control/${path}`;
const money = (amount) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const blank = { sku: '', name: '', category: 'Devices', quantity: 0, reorder_level: 5, unit_price: 0 };

const outages = [
  { id: 'frontend', group: 'Availability', title: 'Frontend down', target: 'IIS application', effects: ['This page becomes unavailable after refresh', 'The API and database keep running', 'Restore from the separate controller page'], signal: 'IIS endpoint or synthetic check fails.' },
  { id: 'api', group: 'Availability', title: 'API down', target: 'Python service', effects: ['Stops the lab-owned Python process', 'Products and requests stop loading', 'PostgreSQL keeps running'], signal: 'API health and proxied requests fail.' },
  { id: 'database', group: 'Availability', title: 'PostgreSQL down', target: 'Docker Compose · postgres', effects: ['Stops the test database container for real', 'The API stays up but inventory returns 503', 'Stored inventory returns after restore'], signal: 'Database health and inventory requests fail.' },
  { id: 'route', group: 'Networking', title: 'API route unavailable', target: 'IIS reverse proxy', effects: ['Points only this app’s proxy at an unused local port', 'The Python API and database keep running', 'Restore puts the original web.config back'], signal: 'IIS API requests fail while Python is healthy.' },
  { id: 'cpu', group: 'Utilization', title: 'CPU pressure', target: 'Bounded Python worker', effects: ['Runs one CPU worker for at most 60 seconds', 'The other tiers remain available', 'Restore stops the worker early'], signal: 'Host CPU utilization rises briefly.' },
  { id: 'disk', group: 'Utilization', title: 'Disk usage increase', target: 'Bounded 128 MB test file', effects: ['Creates a removable file in the lab folder', 'Requires at least 2 GB free before starting', 'Restore removes only this file'], signal: 'Host disk usage rises by about 128 MB.' },
];
const requests = [
  ['healthy', 'Healthy request', 'API', '200'], ['api-error', 'Server error', 'API', '500'],
  ['api-exception', 'Unhandled exception', 'API', '500'], ['slow-api', 'Slow API', 'API', '200 · 2s'],
  ['upstream-unavailable', 'Upstream unavailable', 'API', '503'], ['db-read', 'Read database', 'DATABASE', '200'],
  ['db-write', 'Write database', 'DATABASE', '201'], ['slow-db', 'Slow database query', 'DATABASE', '200 · 2s'],
  ['db-error', 'Database query error', 'DATABASE', '500'],
];

function Pill({ name, status }) {
  return <span className={`pill ${status === 'running' || status === 'ok' ? 'ok' : status === 'unknown' ? 'unknown' : 'down'}`}><i />{name}<span className="sr-only">: {status}</span></span>;
}

function Products({ products, error, refresh, save, remove, saving }) {
  const [search, setSearch] = useState('');
  const [form, setForm] = useState(null);
  const filtered = products.filter((p) => `${p.name} ${p.sku} ${p.category}`.toLowerCase().includes(search.toLowerCase()));
  const low = products.filter((p) => p.quantity > 0 && p.quantity <= p.reorder_level).length;
  const out = products.filter((p) => p.quantity === 0).length;
  const amount = products.reduce((sum, p) => sum + p.quantity * Number(p.unit_price), 0);
  async function submit(event) {
    event.preventDefault();
    if (await save(form.id, { ...form, quantity: Number(form.quantity), reorder_level: Number(form.reorder_level), unit_price: Number(form.unit_price) })) setForm(null);
  }
  return <>
    <div className="page-heading"><div><h1>Products</h1><p>Create, edit and remove inventory items stored in PostgreSQL.</p></div><button disabled={!!error} onClick={() => setForm({ ...blank })}>+ Add product</button></div>
    {error && <div className="banner error" role="alert"><div><strong>Inventory unavailable</strong><span>{error}</span></div><button className="subtle" onClick={refresh}>↻ Retry</button></div>}
    <div className="metrics">{[['Products', products.length, 'inventory lines'], ['Inventory value', money(amount), 'at current prices'], ['Low stock', low, 'at or below reorder level'], ['Out of stock', out, 'need restocking']].map(([name, value, hint]) => <div className="metric" key={name}><span>{name}</span><strong>{error ? '—' : value}</strong><small>{hint}</small></div>)}</div>
    {form && <form className="card product-form" onSubmit={submit}><div className="card-title"><h2>{form.id ? 'Edit product' : 'Add product'}</h2><button type="button" className="text-button" onClick={() => setForm(null)}>Cancel</button></div><div className="form-grid">{[['sku', 'SKU'], ['name', 'Name'], ['category', 'Category'], ['quantity', 'Quantity'], ['reorder_level', 'Reorder level'], ['unit_price', 'Unit price']].map(([key, label]) => <label key={key}>{label}<input required disabled={key === 'sku' && !!form.id} type={['quantity', 'reorder_level', 'unit_price'].includes(key) ? 'number' : 'text'} min={['quantity', 'reorder_level', 'unit_price'].includes(key) ? 0 : undefined} step={key === 'unit_price' ? '0.01' : undefined} value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>)}</div><button disabled={saving}>Save product</button></form>}
    <section className="card"><div className="card-title"><div><h2>Inventory</h2><p>Real records from the test database</p></div><input aria-label="Search products" placeholder="Search products…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>{!error && <div className="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th>Category</th><th>Stock</th><th>Unit price</th><th>Value</th><th>Actions</th></tr></thead><tbody>{filtered.map((p) => <tr key={p.id}><td><strong>{p.name}</strong></td><td>{p.sku}</td><td>{p.category}</td><td><span className={`stock ${p.quantity === 0 ? 'out' : p.quantity <= p.reorder_level ? 'low' : 'in'}`}>{p.quantity === 0 ? 'Out of stock' : p.quantity <= p.reorder_level ? `Low · ${p.quantity}` : `${p.quantity} in stock`}</span></td><td>{money(p.unit_price)}</td><td>{money(p.quantity * Number(p.unit_price))}</td><td><button className="text-button" onClick={() => setForm({ ...p })}>Edit</button><button className="text-button delete" disabled={saving} onClick={() => { if (window.confirm(`Delete ${p.name}?`)) void remove(p.id); }}>Delete</button></td></tr>)}</tbody></table>{!filtered.length && <p className="empty">{products.length ? 'No products match the search.' : 'No products yet.'}</p>}</div>}</section>
  </>;
}

function Simulation({ state, controlBusy, controlMessage, change, run, series, busy, cancel, progress, activity, events, health }) {
  const [group, setGroup] = useState('All simulations');
  const selected = outages.filter((item) => group === 'All simulations' || item.group === group);
  const active = (item) => item.id === 'cpu' || item.id === 'disk' ? state?.[item.id] === 'running' : state?.[item.id === 'route' ? 'route' : item.id] === 'stopped';
  return <>
    <div className="page-heading"><div><h1>Simulation</h1><p>Break one part of the test system on purpose to check monitoring and recovery.</p></div><a className="subtle recovery" href="http://127.0.0.1:8010/" target="_blank" rel="noreferrer">Open recovery page ↗</a></div>
    <div className="banner warning"><div><strong>These simulations are real.</strong><span>Each one changes a component on this test machine. Stops ask for confirmation. The independent recovery page remains at 127.0.0.1:8010.</span></div></div>
    {!state && <div className="banner error">Local controller unavailable. Keep the IIS Test Controller window running.</div>}
    <div className="filter"><label htmlFor="filter">Scenario</label><select id="filter" value={group} onChange={(event) => setGroup(event.target.value)}><option>All simulations</option><option>Availability</option><option>Networking</option><option>Utilization</option></select><span>{selected.length + (group === 'All simulations' || group === 'Availability' ? 1 : 0)} shown</span></div>
    {['Availability', 'Networking', 'Utilization'].map((category) => { const items = selected.filter((item) => item.group === category); return items.length > 0 && <section className="sim-group" key={category}><h2>{category}</h2><div className="sim-grid">{items.map((item) => <article className="sim-card" key={item.id}><div className="sim-head"><span className="sim-icon">{item.id === 'database' ? '▤' : item.id === 'route' ? '⌁' : item.id === 'cpu' ? '◉' : item.id === 'disk' ? '▣' : '◇'}</span><div><h3>{item.title}</h3><small>{item.target}</small></div><span className={`sim-state ${active(item) ? 'active' : ''}`}>{!state ? 'Unknown' : active(item) ? 'Simulating' : 'Normal'}</span></div><ul>{item.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul><p className="signal"><b>ASTRA should notice:</b> {item.signal}</p><div className="button-row"><button className="danger" disabled={!state || controlBusy || active(item)} onClick={() => change(item.id, 'stop')}>Run simulation</button><button className="subtle" disabled={!state || controlBusy || !active(item)} onClick={() => change(item.id, 'restore')}>Restore</button></div>{item.id === 'frontend' && <small>Once this page disappears, restore it from the recovery page.</small>}</article>)}</div></section>; })}
    {(group === 'All simulations' || group === 'Availability') && <section className="sim-group"><h2>Application errors</h2><div className="sim-grid"><article className="sim-card"><div className="sim-head"><span className="sim-icon">!</span><div><h3>Real API exception</h3><small>Python endpoint</small></div></div><ul><li>Raises an actual Python exception</li><li>Returns HTTP 500 and writes an API error log</li><li>The API process stays running</li></ul><p className="signal"><b>ASTRA should notice:</b> API error rate or collected application logs.</p><button className="danger" disabled={busy} onClick={() => run('api-exception')}>Run simulation</button></article></div></section>}
    <p role="status" className="action-message">{controlMessage}</p>
    <section className="card"><div className="card-title"><div><h2>Controlled traffic</h2><p>Run a healthy baseline, then a short error burst through IIS.</p></div></div><div className="button-row"><button disabled={busy} onClick={() => series('healthy', 30, 1000)}>30 healthy requests</button><button className="danger" disabled={busy} onClick={() => series('api-error', 8, 2000)}>8 API errors</button><button className="danger" disabled={busy || health?.database !== 'ok'} onClick={() => series('db-error', 8, 2000)}>8 database errors</button><button className="subtle" disabled={!busy} onClick={cancel}>Stop run</button></div><p role="status">{progress || 'No batch running'}</p></section>
    <section className="card"><div className="card-title"><div><h2>Single requests</h2><p>These go through the IIS proxy.</p></div></div><div className="request-grid">{requests.map(([id, title, tier, expected]) => <article className="request-card" key={id}><div className="request-top"><span>{tier}</span><small>HTTP {expected}</small></div><h3>{title}</h3><button className={expected.startsWith('5') ? 'danger' : ''} disabled={busy} onClick={() => run(id)}>Run request</button></article>)}</div></section>
    <div className="bottom-grid"><section className="card"><h2>Recent browser results</h2>{activity.length ? activity.map((item, index) => <div className="result" key={`${item.at}-${index}`}><span>{item.at}</span><b className={Number(item.status) >= 500 ? 'bad' : 'good'}>{item.status}</b><div><strong>{item.scenario}</strong><small>{item.message}</small></div><span>{item.ms} ms</span></div>) : <p className="empty">Run a scenario to see results.</p>}</section><section className="card"><h2>Recent database writes</h2>{events.length ? events.map((item) => <div className="result" key={item.id}><span>#{item.id}</span><div><strong>{item.scenario}</strong><small>{new Date(item.created_at).toLocaleString()}</small></div></div>) : <p className="empty">Run “Write database” to create a record.</p>}</section></div>
  </>;
}

export default function App() {
  const [page, setPage] = useState(location.hash === '#/simulation' ? 'simulation' : 'products');
  const [health, setHealth] = useState(null);
  const [products, setProducts] = useState([]);
  const [productError, setProductError] = useState('');
  const [events, setEvents] = useState([]);
  const [activity, setActivity] = useState([]);
  const [state, setState] = useState(null);
  const [controlBusy, setControlBusy] = useState(false);
  const [controlMessage, setControlMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [progress, setProgress] = useState('');
  const cancelled = useRef(false);

  useEffect(() => { const navigate = () => setPage(location.hash === '#/simulation' ? 'simulation' : 'products'); addEventListener('hashchange', navigate); return () => removeEventListener('hashchange', navigate); }, []);
  const refresh = useCallback(async () => {
    try { const response = await fetch(api('health'), { cache: 'no-store' }); const body = await response.json(); setHealth(body.api ? body : { api: 'unavailable', database: 'unknown' }); } catch { setHealth({ api: 'unavailable', database: 'unknown' }); }
    try { const response = await fetch(api('products'), { cache: 'no-store' }); const body = await response.json(); if (!response.ok) throw new Error(body.message || `HTTP ${response.status}`); setProducts(body.products || []); setProductError(''); } catch (error) { setProducts([]); setProductError(`The API or PostgreSQL could not load products. ${error.message || String(error)}`); }
    try { const response = await fetch(api('events'), { cache: 'no-store' }); if (response.ok) setEvents((await response.json()).events || []); } catch { /* The last write list remains visible during an outage. */ }
  }, []);
  const refreshState = useCallback(async () => { try { const response = await fetch(controller('status'), { cache: 'no-store' }); if (!response.ok) throw new Error(); setState(await response.json()); } catch { setState(null); } }, []);
  useEffect(() => { void refresh(); void refreshState(); const timer = setInterval(() => { void refresh(); void refreshState(); }, 10000); return () => clearInterval(timer); }, [refresh, refreshState]);

  async function change(tier, action) {
    if (action === 'stop' && !confirm(`Run the ${tier} simulation on this test machine? Recovery: http://127.0.0.1:8010/`)) return;
    setControlBusy(true); setControlMessage(`${action === 'stop' ? 'Starting' : 'Restoring'} ${tier}…`);
    try { const response = await fetch(controller(`${tier}/${action}`), { method: 'POST', headers: { 'X-Lab-Control': 'local-lab' } }); const body = await response.json(); setControlMessage(response.ok ? `${tier} ${action === 'stop' ? 'simulation started' : 'restored'}.` : (body.detail || `HTTP ${response.status}`)); } catch (error) { setControlMessage(`Controller unavailable: ${String(error)}`); } finally { setControlBusy(false); void refreshState(); void refresh(); }
  }
  async function save(id, product) {
    setSaving(true);
    try { const response = await fetch(api(id ? `products/${id}` : 'products'), { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(product) }); const body = await response.json(); if (!response.ok) throw new Error(body.message || `HTTP ${response.status}`); await refresh(); return true; } catch (error) { setProductError(`Could not save product. ${error.message || String(error)}`); return false; } finally { setSaving(false); }
  }
  async function remove(id) {
    setSaving(true);
    try { const response = await fetch(api(`products/${id}`), { method: 'DELETE' }); const body = await response.json(); if (!response.ok) throw new Error(body.message || `HTTP ${response.status}`); await refresh(); } catch (error) { setProductError(`Could not delete product. ${error.message || String(error)}`); } finally { setSaving(false); }
  }
  async function run(id) {
    const start = performance.now(); let entry;
    try { const response = await fetch(api(`scenarios/${id}`), { method: 'POST', cache: 'no-store' }); const body = await response.json().catch(() => ({})); entry = { at: new Date().toLocaleTimeString(), scenario: id, status: response.status, ms: Math.round(performance.now() - start), message: body.message || '' }; if (id.startsWith('db-') && response.ok) void refresh(); } catch (error) { entry = { at: new Date().toLocaleTimeString(), scenario: id, status: 'network error', ms: Math.round(performance.now() - start), message: String(error) }; }
    setActivity((old) => [entry, ...old].slice(0, 50));
  }
  async function series(id, total, gap) { if (busy) return; cancelled.current = false; setBusy(true); try { for (let i = 1; i <= total && !cancelled.current; i++) { await run(id); setProgress(`${id}: ${i}/${total} requests sent`); if (i < total && !cancelled.current) await pause(gap); } if (cancelled.current) setProgress(`${id}: stopped`); } finally { setBusy(false); void refresh(); } }

  return <div className="shell"><aside className="sidebar"><a className="brand" href="#/products"><span className="brand-icon">◇</span><span><strong>Stockroom</strong><small>IIS test inventory</small></span></a><nav><a className={page === 'products' ? 'selected' : ''} href="#/products">◇ <span>Products</span></a><a className={page === 'simulation' ? 'selected' : ''} href="#/simulation">♧ <span>Simulation</span></a></nav><div className="sidebar-foot"><small>LOCAL WINDOWS TEST LAB</small><strong>React · Python · PostgreSQL</strong><span>Real component failures, scoped to this app.</span></div></aside><main className="workspace"><div className="topbar"><span>IIS three-tier test lab / {page === 'products' ? 'Products' : 'Simulation'}</span><div className="pills"><Pill name="Frontend" status={state?.frontend || 'unknown'} /><Pill name="API" status={health?.api || 'unknown'} /><Pill name="PostgreSQL" status={health?.database || 'unknown'} /></div></div>{page === 'products' ? <Products products={products} error={productError} refresh={refresh} save={save} remove={remove} saving={saving} /> : <Simulation state={state} controlBusy={controlBusy} controlMessage={controlMessage} change={change} run={run} series={series} busy={busy} cancel={() => { cancelled.current = true; }} progress={progress} activity={activity} events={events} health={health} />}<footer>Dedicated test machine only. Recovery: <a href="http://127.0.0.1:8010/">127.0.0.1:8010</a>. ASTRA alerts require configured collection and monitors.</footer></main></div>;
}
