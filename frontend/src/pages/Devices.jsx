import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Search, Server, ShieldAlert, SlidersHorizontal, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { CATEGORIES, CONNECTIONS, SUPPORT, categoryIcon, categoryLabel } from '../lib/labels.js'
import DeviceForm from '../components/DeviceForm.jsx'
import { Alert, Badge, Dialog, Empty, ErrorNote, PageHeader, Panel, SkeletonRows, formatDate } from '../components/ui.jsx'

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
            <Empty icon={Server} title="No device selected" />
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
              {selected.connection.method === 'telnet_lab' && <Alert tone="warning">Lab console over telnet – unencrypted.</Alert>}
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
