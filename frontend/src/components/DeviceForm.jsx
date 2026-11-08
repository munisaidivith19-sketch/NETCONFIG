import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { get } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { CATEGORIES, CONNECTIONS } from '../lib/labels.js'
import { Alert, ErrorNote, Field } from './ui.jsx'

const EMPTY = {
  name: '',
  model_id: '',
  mgmt_ip: '',
  location: '',
  tags: '',
  connection: { method: 'ssh', port: 22, serial_port: '', baud: 9600 },
}

function toForm(device) {
  if (!device) return EMPTY
  return {
    name: device.name,
    model_id: device.model_id,
    mgmt_ip: device.mgmt_ip || '',
    location: device.location || '',
    tags: device.tags.join(', '),
    connection: { ...EMPTY.connection, ...device.connection, serial_port: device.connection.serial_port || '' },
  }
}

function toBody(form) {
  const c = form.connection
  const connection = { method: c.method }
  if (c.method === 'ssh' || c.method === 'telnet_lab') connection.port = Number(c.port) || undefined
  if (c.method === 'serial') {
    connection.serial_port = c.serial_port.trim().toUpperCase()
    connection.baud = Number(c.baud)
  }
  return {
    name: form.name.trim(),
    model_id: form.model_id,
    mgmt_ip: form.mgmt_ip.trim() || null,
    location: form.location.trim(),
    tags: form.tags.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean),
    connection,
  }
}

// Add or edit a device. Device passwords are never asked for here: they are entered only at push time.
export default function DeviceForm({ device, onSubmit, onCancel, submitLabel = 'Save device' }) {
  const { can } = useAuth()
  const [form, setForm] = useState(() => toForm(device))
  const [category, setCategory] = useState('')
  const [models, setModels] = useState([])
  const [model, setModel] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    get('/catalog/models', { query: { category, page_size: 200 } }).then((r) => setModels(r.items)).catch(setError)
  }, [category])

  useEffect(() => {
    if (!form.model_id) return setModel(null)
    get(`/catalog/models/${form.model_id}`).then(setModel).catch(() => setModel(null))
  }, [form.model_id])

  const connections = model?.os_driver?.connections?.length ? model.os_driver.connections : ['none']
  useEffect(() => {
    if (model && !connections.includes(form.connection.method)) {
      setForm((f) => ({ ...f, connection: { ...f.connection, method: connections[0] } }))
    }
  }, [model]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const setConn = (k) => (e) => setForm((f) => ({ ...f, connection: { ...f.connection, [k]: e.target.value } }))
  const fields = error?.fields || {}
  const method = form.connection.method
  const tagList = form.tags.split(',').map((t) => t.trim().toLowerCase())
  const productionLocked = !can('admin')

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit(toBody(form))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      {error && <ErrorNote error={error} />}
      <div className="form-grid">
        <Field label="Device name" hint="Letters, digits, . _ - (like a hostname)" error={fields.name}>
          {(p) => <input {...p} className="input" value={form.name} onChange={set('name')} maxLength={63} required />}
        </Field>
        <Field label="Filter models by category">
          {(p) => (
            <select {...p} className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          )}
        </Field>
        <Field label="Model" error={fields.model_id} hint={model ? `${model.brand} · ${model.os_driver?.name}` : 'From the catalog'}>
          {(p) => (
            <select {...p} className="select" value={form.model_id} onChange={set('model_id')} required>
              <option value="">Choose a model…</option>
              {form.model_id && !models.some((m) => m.id === form.model_id) && <option value={form.model_id}>{form.model_id}</option>}
              {models.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.brand_id})</option>)}
            </select>
          )}
        </Field>
        <Field label="Connection" error={fields['connection.method'] || fields.connection}>
          {(p) => (
            <select {...p} className="select" value={method} onChange={setConn('method')}>
              {connections.map((c) => <option key={c} value={c}>{CONNECTIONS[c]}</option>)}
            </select>
          )}
        </Field>
        {(method === 'ssh' || method === 'telnet_lab') && (
          <>
            <Field label="Management IP" error={fields.mgmt_ip} hint="IPv4 or IPv6">
              {(p) => <input {...p} className="input mono" value={form.mgmt_ip} onChange={set('mgmt_ip')} maxLength={45} inputMode="decimal" required />}
            </Field>
            <Field label={method === 'ssh' ? 'SSH port' : 'Console port'} error={fields['connection.port']}>
              {(p) => <input {...p} className="input" type="number" min={1} max={65535} value={form.connection.port} onChange={setConn('port')} />}
            </Field>
          </>
        )}
        {method === 'serial' && (
          <>
            <Field label="COM port" hint="For example COM3 (Device Manager → Ports)" error={fields['connection.serial_port'] || fields.connection}>
              {(p) => <input {...p} className="input mono" value={form.connection.serial_port} onChange={setConn('serial_port')} maxLength={6} placeholder="COM3" />}
            </Field>
            <Field label="Speed (baud)">
              {(p) => (
                <select {...p} className="select" value={form.connection.baud} onChange={setConn('baud')}>
                  {[9600, 19200, 38400, 57600, 115200].map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              )}
            </Field>
            <Field label="Management IP (optional for now)" error={fields.mgmt_ip} hint="Set during first-time setup">
              {(p) => <input {...p} className="input mono" value={form.mgmt_ip} onChange={set('mgmt_ip')} maxLength={45} />}
            </Field>
          </>
        )}
        <Field label="Location" error={fields.location} hint="Optional, e.g. Building A / Rack 2">
          {(p) => <input {...p} className="input" value={form.location} onChange={set('location')} maxLength={64} />}
        </Field>
        <Field label="Tags" error={fields.tags || Object.entries(fields).find(([k]) => k.startsWith('tags.'))?.[1]}
          hint={productionLocked ? 'Comma separated. Only an admin can add or remove “production”.' : 'Comma separated. “production” turns on two-person approval.'}>
          {(p) => <input {...p} className="input" value={form.tags} onChange={set('tags')} placeholder="core, building-a" />}
        </Field>
      </div>
      {method === 'telnet_lab' && (
        <Alert tone="warning">Telnet sends everything unencrypted. It is allowed only for emulator consoles on 127.0.0.1 or private (RFC1918) addresses.</Alert>
      )}
      {tagList.includes('production') && (
        <Alert tone="info"><AlertTriangle size={14} aria-hidden="true" /> Production device: every push needs approval from a second admin.</Alert>
      )}
      <div className="form-actions">
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>}
        <button type="submit" className="btn primary" disabled={busy || !form.name || !form.model_id}>
          {busy ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}
