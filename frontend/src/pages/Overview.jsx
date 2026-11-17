import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, ClipboardCheck, History, Network, RefreshCw, ScanSearch, Server } from 'lucide-react'
import { get, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { categoryLabel } from '../lib/labels.js'
import { STATUS } from '../lib/jobs.js'
import { reveal, stacked } from '../lib/scroll.js'
import TopologyMap from '../components/TopologyMap.jsx'
import { BarList, StackedColumns, TableToggle, TrendLine } from '../components/charts.jsx'
import { Alert, Badge, Empty, ErrorNote, Field, PageHeader, Panel, Skeleton, SkeletonRows, formatDate } from '../components/ui.jsx'

const REFRESH_MS = 30000
const OUTCOMES = [
  { key: 'success', label: 'Succeeded', color: 'var(--chart-good)' },
  { key: 'failed', label: 'Failed or rolled back', color: 'var(--chart-bad)' },
]

function Kpi({ icon: Icon, label, value, note }) {
  return (
    <div className="glass kpi">
      <span className="kpi-label"><span className="kpi-icon"><Icon size={16} aria-hidden="true" /></span>{label}</span>
      <span className="kpi-value">{value}</span>
      {note && <span className="kpi-note">{note}</span>}
    </div>
  )
}

function KpiSkeleton() {
  return (
    <div className="grid kpis" aria-busy="true" aria-label="Loading">
      {[0, 1, 2, 3].map((i) => <div key={i} className="glass kpi"><Skeleton width="60%" /><Skeleton height={30} width="40%" /></div>)}
    </div>
  )
}

// Device login for one read-only discovery. Kept in this component's state only and cleared after the request.
function DiscoverForm({ device, onDone }) {
  const [form, setForm] = useState({ username: '', password: '', enable_secret: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const fields = error?.fields || {}

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = { username: form.username.trim(), password: form.password }
      if (form.enable_secret) body.enable_secret = form.enable_secret
      onDone(await post(`/devices/${device.id}/discover`, body))
    } catch (err) {
      setError(err)
    } finally {
      setForm((f) => ({ ...f, password: '', enable_secret: '' }))
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <p className="faint">
        Runs read-only <span className="mono">show</span> commands to read the model, software version, neighbours
        and VLANs. Nothing on the device is changed and the login is not stored.
      </p>
      <ErrorNote error={error} />
      <div className="form-grid">
        <Field label="Device username" error={fields.username}>
          {(p) => <input {...p} className="input" value={form.username} onChange={set('username')} maxLength={64} autoComplete="off" />}
        </Field>
        <Field label="Device password" error={fields.password}>
          {(p) => <input {...p} className="input" type="password" value={form.password} onChange={set('password')} maxLength={128} autoComplete="off" />}
        </Field>
        <Field label="Enable secret (optional)" error={fields.enable_secret} hint="Only if the device asks for one">
          {(p) => <input {...p} className="input" type="password" value={form.enable_secret} onChange={set('enable_secret')} maxLength={128} autoComplete="off" />}
        </Field>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy || !form.username || !form.password}>
          <ScanSearch size={16} aria-hidden="true" /> {busy ? 'Reading the device…' : 'Read device facts'}
        </button>
      </div>
    </form>
  )
}

function DevicePanel({ id, onChanged }) {
  const { can } = useAuth()
  const [device, setDevice] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setDevice(null)
    setError(null)
    get(`/devices/${id}`).then(setDevice).catch(setError)
  }, [id])

  if (error) return <ErrorNote error={error} />
  if (!device) return <SkeletonRows rows={4} />
  const s = device.status || {}
  const facts = device.facts?.source === 'cli' ? device.facts : null
  const match = facts?.match
  const readable = ['ssh', 'telnet_lab'].includes(device.connection.method) && device.mgmt_ip && device.support !== 'inventory'

  return (
    <div className="stack">
      <div className="row">
        <Badge tone={s.reachable === true ? 'success' : s.reachable === false ? 'danger' : undefined} dot>
          {s.reachable === true ? 'Reachable' : s.reachable === false ? 'Unreachable' : 'Not checked yet'}
        </Badge>
        <Badge>{categoryLabel(device.category)}</Badge>
        {device.production && <Badge tone="warning">production</Badge>}
      </div>
      <dl className="facts">
        <div><dt className="faint">Model (inventory)</dt><dd>{device.model_name}</dd></div>
        <div><dt className="faint">Management IP</dt><dd className="mono">{device.mgmt_ip || '—'}</dd></div>
        <div><dt className="faint">Last check</dt><dd>{formatDate(s.checked_at)}</dd></div>
        {s.latency_ms != null && <div><dt className="faint">Ping</dt><dd>{s.latency_ms} ms</dd></div>}
        {s.reachable === false && s.ping && <div><dt className="faint">Note</dt><dd>Answers ping, but its {device.connection.method === 'ssh' ? 'SSH' : 'console'} port is closed</dd></div>}
      </dl>

      {match?.status === 'mismatch' && <Alert tone="warning" title="Check the model.">{match.message}</Alert>}
      {facts && (
        <dl className="facts">
          <div><dt className="faint">Reported model</dt><dd className="mono">{facts.model || '—'}</dd></div>
          <div><dt className="faint">Software</dt><dd className="mono">{facts.version || '—'}</dd></div>
          <div><dt className="faint">Serial</dt><dd className="mono">{facts.serial || '—'}</dd></div>
          <div><dt className="faint">Read</dt><dd>{formatDate(facts.read_at)}</dd></div>
        </dl>
      )}

      {device.vlans?.length > 0 && (
        <details>
          <summary>VLANs on the device ({device.vlans.length})</summary>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">ID</th><th scope="col">Name</th></tr></thead>
              <tbody>{device.vlans.map((v) => <tr key={v.id}><td className="mono">{v.id}</td><td>{v.name}</td></tr>)}</tbody>
            </table>
          </div>
        </details>
      )}
      {device.neighbors?.length > 0 && (
        <details>
          <summary>Neighbours ({device.neighbors.length})</summary>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Local port</th><th scope="col">Neighbour</th><th scope="col">Its port</th></tr></thead>
              <tbody>
                {device.neighbors.map((n, i) => (
                  <tr key={i}><td className="mono">{n.local}</td><td>{n.remote}</td><td className="mono">{n.port || '—'}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {can('engineer') && readable && <DiscoverForm key={device.id} device={device} onDone={(d) => { setDevice(d); onChanged() }} />}
      {device.category === 'ap' && <p className="faint">Managed by its wireless controller: open it under Devices to configure its switch port.</p>}
      <div className="row">
        <Link className="btn ghost small" to="/devices">Open in Devices</Link>
        {can('engineer') && device.support !== 'inventory' && <Link className="btn ghost small" to={`/configure?device=${device.id}`}>Configure</Link>}
      </div>
    </div>
  )
}

export default function Overview() {
  const { can } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)
  const [selected, setSelected] = useState(null)
  const [notice, setNotice] = useState(null)

  // Background refresh keeps the current frame on screen (no flash, no skeleton) and only swaps the numbers.
  const load = useCallback(() => get('/overview').then((d) => { setData(d); setError(null) }).catch(setError), [])

  useEffect(() => {
    load()
    // No polling while the tab is hidden; coming back refreshes at once.
    const t = setInterval(() => { if (!document.hidden) load() }, REFRESH_MS)
    const onShow = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', onShow)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onShow) }
  }, [load])

  async function refresh() {
    setNotice(null)
    setChecking(true)
    try {
      await post('/overview/refresh')
      setNotice('Checking every device now. The map updates in a few seconds.')
      setTimeout(() => load().finally(() => setChecking(false)), 5000)
    } catch (err) {
      setError(err)
      setChecking(false)
    }
  }

  // On a phone the device panel sits below the map: bring it into view when a device is picked.
  function select(id) {
    setSelected(id)
    if (stacked()) requestAnimationFrame(() => reveal(document.getElementById('device-panel')))
  }

  const k = data?.kpis
  const nodes = data?.topology.nodes || []
  const realNodes = nodes.filter((n) => !n.external)

  return (
    <>
      <PageHeader title="Overview" subtitle={data?.last_poll ? `Status checked ${formatDate(data.last_poll)}` : 'Live status of your network'}>
        {can('engineer') && (
          <button type="button" className="btn" onClick={refresh} disabled={checking} aria-busy={checking}>
            <RefreshCw size={16} aria-hidden="true" className={checking ? 'spin' : undefined} /> {checking ? 'Checking…' : 'Check status now'}
          </button>
        )}
      </PageHeader>
      {notice && <Alert tone="info">{notice}</Alert>}
      <ErrorNote error={error} />

      {!data ? <KpiSkeleton /> : (
        <div className="grid kpis">
          <Kpi icon={Server} label="Devices reachable" value={`${k.up} / ${k.devices}`}
            note={k.devices ? `${k.down} down · ${k.unknown} not checked` : 'No devices yet'} />
          <Kpi icon={Activity} label="Jobs in the last 7 days" value={k.jobs_7d}
            note={k.success_rate_7d == null ? 'None finished yet' : `${k.success_rate_7d}% succeeded · ${k.failed_7d} failed or rolled back`} />
          <Kpi icon={ClipboardCheck} label="Waiting" value={k.waiting}
            note={k.running ? `${k.running} running now` : 'For approval or to be run'} />
          <Kpi icon={AlertTriangle} label="Model warnings" value={k.model_mismatches}
            note={k.model_mismatches ? 'Device reports a different model or OS' : 'Read device facts to check'} />
        </div>
      )}

      <div className="grid two">
        <Panel title="Network map" subtitle="Links come from LLDP/CDP (read device facts) and access point uplinks.">
          {!data ? <Skeleton height={260} /> : realNodes.length === 0 ? (
            <Empty icon={Network} title="No devices yet" action={<Link className="btn primary" to="/devices">Add a device</Link>}>
              Add your switches and routers, then read their facts to draw the map.
            </Empty>
          ) : (
            <div className="stack">
              <TopologyMap nodes={nodes} links={data.topology.links} selectedId={selected} onSelect={select} />
              {data.topology.links.length === 0 && (
                <p className="faint">No links yet: select a device and choose <strong>Read device facts</strong> to find its neighbours.</p>
              )}
            </div>
          )}
        </Panel>
        <Panel title="Device" id="device-panel">
          {selected ? <DevicePanel id={selected} onChanged={load} /> : (
            <Empty icon={Server} title="No device selected">Select a device on the map to see its status, facts and VLANs.</Empty>
          )}
        </Panel>
      </div>

      <div className="grid halves">
        <Panel title="Jobs per day" subtitle="Last 14 days, by result">
          {!data ? <Skeleton height={180} /> : (
            <>
              <StackedColumns data={data.jobs_by_day} series={OUTCOMES} extra={[{ key: 'other', label: 'Other (waiting, cancelled, expired)' }]}
                label="Jobs per day over the last 14 days, succeeded and failed" />
              <TableToggle caption="Jobs per day" columns={['Day', 'Succeeded', 'Failed or rolled back', 'Other']}
                rows={data.jobs_by_day.map((d) => [d.date, d.success, d.failed, d.other])} />
            </>
          )}
        </Panel>
        <Panel title="Reachable devices" subtitle="Last 24 hours">
          {!data ? <Skeleton height={160} /> : data.status_history.length === 0 ? (
            <Empty icon={Activity} title="No status checks yet">Device status is checked every minute while NetConfig Studio runs. The first results appear shortly after you add a device.</Empty>
          ) : (
            <>
              <TrendLine points={data.status_history.map((s) => ({ at: s.at, value: s.up }))} max={k.devices}
                label="Reachable devices over the last 24 hours" valueLabel="devices reachable" />
              <TableToggle caption="Reachable devices" columns={['Time', 'Reachable', 'Down', 'Not checked']}
                rows={data.status_history.map((s) => [formatDate(s.at), s.up, s.down, s.unknown])} />
            </>
          )}
        </Panel>
      </div>

      <div className="grid halves">
        <Panel title="Devices by category">
          {!data ? <SkeletonRows rows={3} /> : Object.keys(data.devices_by_category).length === 0 ? <p className="faint">No devices yet.</p> : (
            <BarList label="Devices by category" items={Object.entries(data.devices_by_category)
              .sort((a, b) => b[1] - a[1]).map(([c, n]) => ({ label: categoryLabel(c), value: n }))} />
          )}
        </Panel>
        <Panel title="Recent jobs" actions={<Link className="btn ghost small" to="/history"><History size={14} aria-hidden="true" /> History</Link>}>
          {!data ? <SkeletonRows rows={3} /> : data.recent_jobs.length === 0 ? (
            <Empty icon={History} title="No jobs yet">A job is created when you push a change from Configure.</Empty>
          ) : (
            <ul className="recent-list">
              {data.recent_jobs.map((j) => (
                <li key={j.id}>
                  <Link to={`/history/${j.id}`}>{j.devices.join(', ') || 'Job'}</Link>
                  <Badge tone={STATUS[j.status]?.tone || j.status}>{STATUS[j.status]?.label || j.status}</Badge>
                  <span className="faint">{formatDate(j.created_at)} · {j.requested_by}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  )
}
