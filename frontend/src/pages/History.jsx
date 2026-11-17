import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, History as HistoryIcon } from 'lucide-react'
import JobView, { StatusBadge } from '../components/JobView.jsx'
import { Empty, ErrorNote, PageHeader, Panel, SkeletonRows, formatDate } from '../components/ui.jsx'
import { get } from '../lib/api.js'
import { KIND, STATUS, deviceNames, isRunning } from '../lib/jobs.js'
import { useJob } from '../lib/useJob.js'

const PAGE_SIZE = 25

function JobList() {
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    let timer
    const load = () =>
      get('/jobs', { query: { status, kind, page, page_size: PAGE_SIZE }, signal: ctrl.signal })
        .then((d) => {
          setData(d)
          setError(null)
          // Refresh while something is pushing so the list does not show stale states.
          if (d.items.some((j) => isRunning(j.status))) timer = setTimeout(load, 3000)
        })
        .catch((e) => e.name !== 'AbortError' && setError(e))
    load()
    return () => {
      ctrl.abort()
      clearTimeout(timer)
    }
  }, [status, kind, page])

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  return (
    <>
      <PageHeader title="History" subtitle="Every push job: who asked, who approved, what was sent and what the device said." />
      <ErrorNote error={error} />
      <Panel
        title="Jobs"
        actions={
          <>
            <label className="sr-only" htmlFor="f-status">Status</label>
            <select id="f-status" className="select" value={status} onChange={(e) => { setPage(1); setStatus(e.target.value) }}>
              <option value="">Any status</option>
              {Object.entries(STATUS).map(([id, s]) => <option key={id} value={id}>{s.label}</option>)}
            </select>
            <label className="sr-only" htmlFor="f-kind">Kind</label>
            <select id="f-kind" className="select" value={kind} onChange={(e) => { setPage(1); setKind(e.target.value) }}>
              <option value="">Any kind</option>
              {Object.entries(KIND).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </>
        }
      >
        {!data ? (
          <SkeletonRows rows={5} />
        ) : data.items.length === 0 ? (
          <Empty icon={HistoryIcon} title={status || kind ? 'No jobs match these filters' : 'No jobs yet'}
            action={!status && !kind ? <Link className="btn primary" to="/configure">Configure a device</Link> : null}>
            {!status && !kind && 'Jobs appear here once you create one in Configure.'}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Device</th>
                    <th scope="col">Status</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Requested by</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((j) => (
                    <tr key={j.id}>
                      <td className="faint" style={{ whiteSpace: 'nowrap' }}>{formatDate(j.created_at)}</td>
                      <td><Link className="cell-title" to={`/history/${j.id}`}>{deviceNames(j)}</Link></td>
                      <td><StatusBadge status={j.status} /></td>
                      <td className="faint">{KIND[j.kind] || KIND.push}</td>
                      <td>{j.requested_by.username}</td>
                      <td className="faint">{j.note || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row between" style={{ marginTop: 'var(--space-4)' }}>
              <span className="faint">{data.total} jobs · page {page} of {pages}</span>
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

function JobPage({ jobId }) {
  const { job, setJob, error } = useJob(jobId)
  return (
    <>
      <PageHeader title={job?.kind && job.kind !== 'push' ? KIND[job.kind] : 'Push job'} subtitle={job ? `${deviceNames(job, 3)} · ${formatDate(job.created_at)}` : 'Loading…'}>
        <Link className="btn" to="/history"><ArrowLeft size={18} aria-hidden="true" /> All jobs</Link>
      </PageHeader>
      <ErrorNote error={error} />
      {!job && !error && <Panel><SkeletonRows rows={6} /></Panel>}
      {job && <JobView job={job} setJob={setJob} />}
    </>
  )
}

export default function History() {
  const { jobId } = useParams()
  return jobId ? <JobPage key={jobId} jobId={jobId} /> : <JobList />
}
