import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cable, Camera, Pencil, Plus, Search, Server, ShieldAlert, SlidersHorizontal, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { CATEGORIES, CONNECTIONS, SUPPORT, categoryIcon, categoryLabel } from '../lib/labels.js'
import DeviceForm from '../components/DeviceForm.jsx'
import { Alert, Badge, Dialog, Empty, ErrorNote, Field, NO_SAVE, PageHeader, Panel, SkeletonRows, TelnetAlert, formatDate } from '../components/ui.jsx'

const FACT_LABELS = [['manufacturer', 'Manufacturer'], ['model', 'Model'], ['firmwareversion', 'Firmware'],
  ['version', 'Software'], ['serialnumber', 'Serial number'], ['serial', 'Serial number'], ['hostname', 'Host name']]

// Read-only facts read from the device (ONVIF for cameras, "show version" for switches and routers).
function Facts({ facts }) {
  if (!facts) return null
  const rows = FACT_LABELS.filter(([k]) => facts[k])
  if (!rows.length) return null
  return (
    <div className="stack">
      <h3 className="faint" style={{ margin: 0, fontSize: 'var(--text-sm)' }}>
        Read from the device ({facts.source === 'onvif' ? 'ONVIF' : 'show commands'}, {formatDate(facts.read_at)})
      </h3>
      <dl className="facts">
        {rows.map(([k, label]) => (
          <div key={k}><dt className="faint">{label}</dt><dd className="mono">{facts[k]}</dd></div>
        ))}
      </dl>
    </div>
  )
}

// Camera login for one ONVIF read. It lives in this component's state only and is cleared after the request.
function OnvifRead({ device, onDone }) {
  const [form, setForm] = useState({ username: '', password: '', port: '80' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const fields = error?.fields || {}
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const updated = await post(`/devices/${device.id}/onvif`, { username: form.username.trim(), password: form.password, port: Number(form.port) || 80 })
      onDone(updated)
    } catch (err) {
      setError(err)
    } finally {
      setForm((f) => ({ ...f, password: '' }))
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit} noValidate>
      <p className="faint" style={{ margin: 0 }}>
        Reads manufacturer, model, firmware and serial number over ONVIF. Nothing on the camera is changed and the
        login is not stored.
      </p>
      <ErrorNote error={error} />
      <div className="form-grid">
        <Field label="Camera user" error={fields.username}>
          {(p) => <input {...p} className="input" value={form.username} onChange={set('username')} maxLength={64} {...NO_SAVE} required />}
        </Field>
        <Field label="Camera password" error={fields.password}>
          {(p) => <input {...p} className="input" type="password" value={form.password} onChange={set('password')} maxLength={128} {...NO_SAVE} required />}
        </Field>
        <Field label="HTTP port" error={fields.port}>
          {(p) => <input {...p} className="input" type="number" min={1} max={65535} value={form.port} onChange={set('port')} />}
        </Field>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn" disabled={busy || !form.username || !form.password}>
          <Camera size={16} aria-hidden="true" /> {busy ? 'Reading…' : 'Read camera information'}
        </button>
      </div>
    </form>
  )
}

function UplinkInfo({ device, can }) {
  const [sw, setSw] = useState(null)
  useEffect(() => {
    if (!device.uplink) return setSw(null)
    get(`/devices/${device.uplink.device_id}`).then(setSw).catch(() => setSw(null))
  }, [device.uplink])
  const isAp = device.category === 'ap'
  return (
    <>
      {isAp && (
        <Alert tone="info" title="Managed by its wireless controller.">
          NetConfig Studio does not configure the access point itself. It configures the switch port the access point
          is plugged into.
        </Alert>
      )}
      {!device.uplink ? (
        <p className="faint" style={{ margin: 0 }}>No uplink switch port recorded. Edit the device to add one.</p>
      ) : (
        <div className="row">
          <span>
            <Cable size={16} aria-hidden="true" /> Plugged into{' '}
            <strong>{sw?.name || 'a switch'}</strong> port <span className="mono">{device.uplink.interface}</span>
          </span>
          {can('engineer') && sw && sw.support !== 'inventory' && (
            <Link className="btn primary"
              to={`/configure?${new URLSearchParams({ device: sw.id, port: device.uplink.interface, for: device.name })}`}>
              <SlidersHorizontal size={16} aria-hidden="true" /> Configure switch port
            </Link>
          )}
        </div>
      )}
    </>
  )
}

function StatusBadge({ status }) {
  if (status?.reachable === true) return <Badge tone="success" dot>Reachable</Badge>
  if (status?.reachable === false) return <Badge tone="danger" dot>Unreachable</Badge>
  return <Badge dot>Not checked</Badge>
}

export default function Devices() {
  const { can } = useAuth()
  const [filters, setFilters] = useState({ q: '', category: '', tag: '' })
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // null | 'new' | device
  const [selected, setSelected] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = useCallback(() => {
    get('/devices', { query: { ...filters, q: filters.q.trim(), page_size: 200 } })
      .then((r) => {
        setData(r)
        setSelected((s) => (s ? r.items.find((d) => d.id === s.id) || null : null))
      })
      .catch(setError)
  }, [filters])

  useEffect(() => {
    const t = setTimeout(load, 200)
    return () => clearTimeout(t)
  }, [load])

  async function save(body) {
    if (editing === 'new') {
      const dev = await post('/devices', body)
      setNotice(`Added ${dev.name}.`)
    } else {
      const dev = await patch(`/devices/${editing.id}`, body)
      setNotice(`Saved ${dev.name}.`)
    }
    setEditing(null)
    load()
  }

  async function remove(d) {
    if (!window.confirm(`Remove ${d.name} from the inventory? The device itself is not changed.`)) return
    try {
      await del(`/devices/${d.id}`)
      setNotice(`Removed ${d.name}.`)
      setSelected(null)
      load()
    } catch (err) {
      setError(err)
    }
  }

  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: k === 'q' ? e.target.value.replace(/[^A-Za-z0-9._:-]/g, '') : e.target.value }))

  return (
    <>
      <PageHeader title="Devices" subtitle="Your inventory. NetConfig Studio never stores device passwords.">
        {can('engineer') && (
          <button type="button" className="btn primary" onClick={() => setEditing('new')}>
            <Plus size={18} aria-hidden="true" /> Add device
          </button>
        )}
      </PageHeader>
      {notice && <Alert tone="success">{notice}</Alert>}
      <ErrorNote error={error} />

      <div className="grid two">
        <Panel
          title="Inventory"
          subtitle={data ? `${data.total} device${data.total === 1 ? '' : 's'}` : undefined}
          actions={
            <>
              <div className="search">
                <Search size={16} aria-hidden="true" />
                <label className="sr-only" htmlFor="dev-search">Search by name or IP</label>
                <input id="dev-search" className="input" placeholder="Name or IP" value={filters.q} onChange={set('q')} maxLength={63} />
              </div>
              <label className="sr-only" htmlFor="dev-cat">Category</label>
              <select id="dev-cat" className="select" value={filters.category} onChange={set('category')}>
                <option value="">All categories</option>
                {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </>
          }
        >
          {!data ? (
            <SkeletonRows rows={5} />
          ) : data.items.length === 0 ? (
            <Empty icon={Server} title={filters.q || filters.category ? 'No devices match' : 'No devices yet'}
              action={can('engineer') && !filters.q && !filters.category && (
                <button type="button" className="btn primary" onClick={() => setEditing('new')}>
                  <Plus size={18} aria-hidden="true" /> Add your first device
                </button>
              )}>
              {filters.q || filters.category ? 'Try a different search.' : 'Add a switch, router or lab emulator to get started.'}
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Device</th>
                    <th scope="col">Model</th>
                    <th scope="col">Management</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((d) => {
                    const Icon = categoryIcon(d.category)
                    return (
                      <tr key={d.id} className={`clickable ${selected?.id === d.id ? 'selected' : ''}`} onClick={() => setSelected(d)}>
                        <td>
                          <button type="button" className="btn ghost small" onClick={() => setSelected(d)} aria-pressed={selected?.id === d.id}>
                            <Icon size={16} aria-hidden="true" />
                            <span className="cell-title">{d.name}</span>
                          </button>
                          {d.production && <Badge tone="warning">production</Badge>}
                        </td>
                        <td>{d.model_name}<div className="faint">{d.brand}</div></td>
                        <td className="mono">{d.mgmt_ip || d.connection.serial_port || '—'}</td>
                        <td><StatusBadge status={d.status} /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title={selected ? selected.name : 'Device details'} subtitle={selected ? `${selected.brand} ${selected.model_name}` : 'Select a device.'}>
          {!selected ? (
            <Empty icon={Server} title="No device selected">Select a device in the list to see its details, facts and uplink.</Empty>
          ) : (
            <div className="stack">
              <div className="row">
                <Badge tone={SUPPORT[selected.support]?.tone}>{SUPPORT[selected.support]?.label}</Badge>
                <Badge>{categoryLabel(selected.category)}</Badge>
                {selected.production && <Badge tone="warning"><ShieldAlert size={12} aria-hidden="true" /> production</Badge>}
              </div>
              <dl className="stack" style={{ margin: 0 }}>
                <div><dt className="faint">OS driver</dt><dd style={{ margin: 0 }}>{selected.os_name}</dd></div>
                <div><dt className="faint">Connection</dt><dd style={{ margin: 0 }}>{CONNECTIONS[selected.connection.method]}{selected.connection.port ? ` · port ${selected.connection.port}` : ''}{selected.connection.serial_port ? ` · ${selected.connection.serial_port} @ ${selected.connection.baud}` : ''}</dd></div>
                <div><dt className="faint">Management IP</dt><dd style={{ margin: 0 }} className="mono">{selected.mgmt_ip || '—'}</dd></div>
                <div><dt className="faint">Location</dt><dd style={{ margin: 0 }}>{selected.location || '—'}</dd></div>
                <div><dt className="faint">Tags</dt><dd style={{ margin: 0 }}>{selected.tags.length ? selected.tags.join(', ') : '—'}</dd></div>
                <div><dt className="faint">Added</dt><dd style={{ margin: 0 }}>{formatDate(selected.created_at)}</dd></div>
              </dl>
              {selected.connection.method === 'telnet_lab' && <TelnetAlert />}
              {(selected.category === 'ap' || selected.category === 'camera') && <UplinkInfo device={selected} can={can} />}
              <Facts facts={selected.facts} />
              {selected.category === 'camera' && can('engineer') && selected.mgmt_ip && (
                <OnvifRead key={selected.id} device={selected} onDone={(d) => { setSelected(d); setNotice(`Read the camera information of ${d.name}.`); load() }} />
              )}
              <div className="row">
                {can('engineer') && selected.support !== 'inventory' && (
                  <Link className="btn primary" to={`/configure?device=${selected.id}`}>
                    <SlidersHorizontal size={16} aria-hidden="true" /> Configure
                  </Link>
                )}
                {can('engineer') && (
                  <button type="button" className="btn" onClick={() => setEditing(selected)}>
                    <Pencil size={16} aria-hidden="true" /> Edit
                  </button>
                )}
                {can('admin') && (
                  <button type="button" className="btn danger" onClick={() => remove(selected)}>
                    <Trash2 size={16} aria-hidden="true" /> Remove
                  </button>
                )}
              </div>
            </div>
          )}
        </Panel>
      </div>

      {editing && (
        <Dialog title={editing === 'new' ? 'Add device' : `Edit ${editing.name}`} onClose={() => setEditing(null)}>
          <DeviceForm device={editing === 'new' ? null : editing} onSubmit={save} onCancel={() => setEditing(null)}
            submitLabel={editing === 'new' ? 'Add device' : 'Save changes'} />
        </Dialog>
      )}
    </>
  )
}
