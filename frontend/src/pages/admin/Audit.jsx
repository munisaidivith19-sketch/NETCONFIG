import { useEffect, useState } from 'react'
import { ScrollText, ShieldCheck, ShieldX } from 'lucide-react'
import { get } from '../../lib/api.js'
import { Alert, Badge, Empty, ErrorNote, PageHeader, Panel, SkeletonRows, formatDate } from '../../components/ui.jsx'

const PAGE_SIZE = 50
const ACTION_FILTERS = [
  ['', 'All actions'],
  ['auth', 'Sign-ins'],
  ['user', 'User changes'],
  ['device', 'Devices'],
  ['plan', 'Plans and previews'],
  ['job', 'Pushes and approvals'],
  ['hostkey', 'SSH host keys'],
]

function summary(details) {
  if (!details) return ''
  return Object.entries(details)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' · ')
}

export default function Audit() {
  const [filters, setFilters] = useState({ action: '', result: '', user: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [chain, setChain] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    setData(null)
    get('/audit', { query: { ...filters, page, page_size: PAGE_SIZE }, signal: ctrl.signal })
      .then(setData)
      .catch((e) => e.name !== 'AbortError' && setError(e))
    return () => ctrl.abort()
  }, [filters, page])

  useEffect(() => {
    get('/audit/verify').then(setChain).catch(() => setChain(null))
  }, [])

  const set = (k) => (e) => {
    setPage(1)
    setFilters((f) => ({ ...f, [k]: e.target.value }))
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only record of sign-ins, changes, previews and pushes." />
      {chain && (chain.ok ? (
        <Alert tone="success"><ShieldCheck size={16} aria-hidden="true" /> Hash chain intact – no entry has been changed or removed.</Alert>
      ) : (
        <Alert tone="danger"><ShieldX size={16} aria-hidden="true" /> Hash chain broken at entry #{chain.first_bad_seq}. The log may have been edited.</Alert>
      ))}
      <ErrorNote error={error} />
      <Panel
        title="Entries"
        actions={
          <>
            <label className="sr-only" htmlFor="f-action">Action</label>
            <select id="f-action" className="select" value={filters.action} onChange={set('action')}>
              {ACTION_FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <label className="sr-only" htmlFor="f-result">Result</label>
            <select id="f-result" className="select" value={filters.result} onChange={set('result')}>
              <option value="">Any result</option>
              <option value="ok">ok</option>
              <option value="denied">denied</option>
              <option value="failed">failed</option>
            </select>
          </>
        }
      >
        {!data ? (
          <SkeletonRows rows={6} />
        ) : data.items.length === 0 ? (
          <Empty icon={ScrollText} title="Nothing recorded for these filters" />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">When</th>
                    <th scope="col">Who</th>
                    <th scope="col">Action</th>
                    <th scope="col">Result</th>
                    <th scope="col">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.seq}>
                      <td className="faint mono">{e.seq}</td>
                      <td className="faint" style={{ whiteSpace: 'nowrap' }}>{formatDate(e.at)}</td>
                      <td>{e.username || <span className="faint">system</span>}</td>
                      <td className="mono">{e.action}</td>
                      <td><Badge tone={e.result}>{e.result}</Badge></td>
                      <td className="faint">{[e.target?.id && `target: ${e.target.id}`, summary(e.details)].filter(Boolean).join(' · ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row between" style={{ marginTop: 16 }}>
              <span className="faint">{data.total} entries · page {page} of {pages}</span>
              <div className="row">
                <button className="btn small" type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button className="btn small" type="button" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </Panel>
    </>
  )
}
