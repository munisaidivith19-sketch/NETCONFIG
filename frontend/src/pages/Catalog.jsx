import { useEffect, useMemo, useState } from 'react'
import { BookOpen, Check, Minus, Search } from 'lucide-react'
import { get } from '../lib/api.js'
import { CAPABILITIES, CATEGORIES, SUPPORT, categoryLabel } from '../lib/labels.js'
import { Alert, Badge, Empty, ErrorNote, PageHeader, Panel, SkeletonRows } from '../components/ui.jsx'

export default function Catalog() {
  const [category, setCategory] = useState('')
  const [brand, setBrand] = useState('')
  const [q, setQ] = useState('')
  const [brands, setBrands] = useState([])
  const [models, setModels] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [drivers, setDrivers] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    get('/catalog/os-drivers').then(setDrivers).catch(setError)
  }, [])

  useEffect(() => {
    get('/catalog/brands', { query: { category } }).then(setBrands).catch(setError)
  }, [category])

  useEffect(() => {
    const ctrl = new AbortController()
    const timer = setTimeout(() => {
      get('/catalog/models', { query: { category, brand_id: brand, q: q.trim(), page_size: 200 }, signal: ctrl.signal })
        .then((r) => setModels(r.items))
        .catch((e) => e.name !== 'AbortError' && setError(e))
    }, 200)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [category, brand, q])

  useEffect(() => {
    if (!selected) return
    setDetail(null)
    get(`/catalog/models/${selected}`).then(setDetail).catch(setError)
  }, [selected])

  const brandName = useMemo(() => Object.fromEntries(brands.map((b) => [b.id, b.name])), [brands])

  return (
    <>
      <PageHeader title="Catalog" subtitle="Category → brand → series → model. Commands depend on the OS driver, not the model." />
      <Alert tone="warning">Sample data: port counts and names are unverified examples. Check the datasheet before relying on them.</Alert>
      <ErrorNote error={error} />

      <div className="choice-grid" role="group" aria-label="Category">
        <button type="button" className="choice" aria-pressed={category === ''} onClick={() => { setCategory(''); setBrand('') }}>
          <BookOpen size={20} aria-hidden="true" />
          <strong>All categories</strong>
        </button>
        {CATEGORIES.map(({ id, label, icon: Icon, hint }) => (
          <button key={id} type="button" className="choice" aria-pressed={category === id}
            onClick={() => { setCategory(id); setBrand('') }}>
            <Icon size={20} aria-hidden="true" />
            <strong>{label}</strong>
            <small>{hint}</small>
          </button>
        ))}
      </div>

      <div className="grid two">
        <Panel
          title="Models"
          actions={
            <>
              <label className="sr-only" htmlFor="brand-filter">Brand</label>
              <select id="brand-filter" className="select" value={brand} onChange={(e) => setBrand(e.target.value)}>
                <option value="">All brands</option>
                {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <div className="search">
                <Search size={16} aria-hidden="true" />
                <label className="sr-only" htmlFor="model-search">Search models</label>
                <input id="model-search" className="input" placeholder="Search models" value={q}
                  onChange={(e) => setQ(e.target.value.replace(/[^A-Za-z0-9 ._+/-]/g, ''))} maxLength={40} />
              </div>
            </>
          }
        >
          {!models ? (
            <SkeletonRows rows={6} />
          ) : models.length === 0 ? (
            <Empty icon={BookOpen} title="No models match">Try another category, brand or search.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Model</th>
                    <th scope="col">Brand</th>
                    <th scope="col">Category</th>
                    <th scope="col">Ports</th>
                    <th scope="col">PoE</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.id} className={`clickable ${selected === m.id ? 'selected' : ''}`}
                      onClick={() => setSelected(m.id)}>
                      <td>
                        <button type="button" className="btn ghost small" onClick={() => setSelected(m.id)}
                          aria-pressed={selected === m.id}>
                          <span className="cell-title">{m.name}</span>
                        </button>
                      </td>
                      <td>{brandName[m.brand_id] || m.brand_id}</td>
                      <td>{categoryLabel(m.category)}</td>
                      <td>{m.ports}{m.uplinks ? ` + ${m.uplinks} uplinks` : ''}</td>
                      <td>{m.poe ? 'Yes' : 'No'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title={detail ? detail.name : 'Model details'} subtitle={detail ? `${detail.brand} · ${detail.series}` : 'Select a model to see its driver and capabilities.'}>
          {!selected ? (
            <Empty icon={BookOpen} title="No model selected" />
          ) : !detail ? (
            <SkeletonRows rows={5} />
          ) : (
            <ModelDetail detail={detail} />
          )}
        </Panel>
      </div>

      <Panel title="OS drivers" subtitle="One driver per OS family generates the commands for every model that uses it.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Driver</th>
                <th scope="col">Support</th>
                <th scope="col">Apply mode</th>
                <th scope="col">Rollback</th>
                <th scope="col">Save</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((d) => (
                <tr key={d.id}>
                  <td><span className="cell-title">{d.name}</span><div className="faint mono">{d.id}</div></td>
                  <td><Badge tone={SUPPORT[d.support]?.tone}>{SUPPORT[d.support]?.label || d.support}</Badge></td>
                  <td>{d.apply_mode}</td>
                  <td className="mono">{d.rollback}</td>
                  <td className="mono">{d.save_command || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}

function ModelDetail({ detail }) {
  const driver = detail.os_driver
  const caps = new Set(detail.capabilities)
  return (
    <div className="stack">
      <div className="row">
        <Badge tone={SUPPORT[driver?.support]?.tone}>{SUPPORT[driver?.support]?.label || 'Unknown'}</Badge>
        <Badge>{categoryLabel(detail.category)}</Badge>
        <Badge>Layer {detail.layer}</Badge>
        {detail.poe && <Badge tone="info">PoE</Badge>}
      </div>
      <dl className="stack" style={{ margin: 0 }}>
        <div><dt className="faint">OS driver</dt><dd style={{ margin: 0 }}>{driver?.name} <span className="faint mono">({driver?.netmiko_device_type || 'n/a'})</span></dd></div>
        <div><dt className="faint">Ports</dt><dd style={{ margin: 0 }}>{detail.ports} {detail.uplinks ? `+ ${detail.uplinks} uplinks` : ''}</dd></div>
        {detail.port_examples?.length > 0 && (
          <div><dt className="faint">Port names</dt><dd style={{ margin: 0 }} className="mono">{detail.port_examples.join(' … ')}</dd></div>
        )}
        {driver?.note && <div><dt className="faint">Note</dt><dd style={{ margin: 0 }}>{driver.note}</dd></div>}
      </dl>
      <div>
        <h3 style={{ marginBottom: 8 }}>Capabilities</h3>
        <ul className="choice-grid" style={{ listStyle: 'none', padding: 0, margin: 0, gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}>
          {CAPABILITIES.map(([id, label]) => (
            <li key={id} className="row" style={{ gap: 6 }}>
              {caps.has(id)
                ? <Check size={16} aria-hidden="true" style={{ color: 'var(--success)' }} />
                : <Minus size={16} aria-hidden="true" style={{ color: 'var(--text-faint)' }} />}
              <span className={caps.has(id) ? '' : 'faint'}>{label}</span>
              <span className="sr-only">{caps.has(id) ? 'supported' : 'not supported'}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
