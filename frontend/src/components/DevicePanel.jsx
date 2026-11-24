// The device selected on a network map (Overview and Topology): status, inventory and read facts, VLANs,
// neighbours, and the read-only "Read device facts" form.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ScanSearch } from 'lucide-react'
import { get, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { categoryLabel } from '../lib/labels.js'
import { Alert, Badge, ErrorNote, Field, NO_SAVE, SecretInput, SkeletonRows, formatDate } from './ui.jsx'

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
          {(p) => <input {...p} className="input" value={form.username} onChange={set('username')} maxLength={64} {...NO_SAVE} />}
        </Field>
        <Field label="Device password" error={fields.password}>
          {(p) => <SecretInput {...p} value={form.password} onChange={set('password')} />}
        </Field>
        <Field label="Enable secret (optional)" error={fields.enable_secret} hint="Only if the device asks for one">
          {(p) => <SecretInput {...p} value={form.enable_secret} onChange={set('enable_secret')} />}
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

export default function DevicePanel({ id, onChanged }) {
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
