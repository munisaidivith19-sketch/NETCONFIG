import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, History as HistoryIcon } from 'lucide-react'
import JobView, { StatusBadge } from '../components/JobView.jsx'
import { Empty, ErrorNote, PageHeader, Panel, SkeletonRows, formatDate } from '../components/ui.jsx'
import { get } from '../lib/api.js'
import { STATUS, isRunning } from '../lib/jobs.js'
import { useJob } from '../lib/useJob.js'

const PAGE_SIZE = 25

function JobList() {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    let timer
    const load = () =>
      get('/jobs', { query: { status, page, page_size: PAGE_SIZE }, signal: ctrl.signal })
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
  }, [status, page])

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
          </>
        }
      >
        {!data ? (
          <SkeletonRows rows={5} />
        ) : data.items.length === 0 ? (
          <Empty icon={HistoryIcon} title={status ? 'No jobs with this status' : 'No pushes yet'}
            action={!status ? <Link className="btn primary" to="/configure">Configure a device</Link> : null}>
            {!status && 'Jobs appear here once you create one in Configure.'}
          </Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Device</th>
                    <th scope="col">Requested by</th>
                    <th scope="col">Status</th>
                    <th scope="col">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((j) => (
                    <tr key={j.id}>
                      <td className="faint" style={{ whiteSpace: 'nowrap' }}>{formatDate(j.created_at)}</td>
                      <td><Link className="cell-title" to={`/history/${j.id}`}>{j.steps[0].device_name}</Link></td>
                      <td>{j.requested_by.username}</td>
                      <td><StatusBadge status={j.status} /></td>
                      <td className="faint">{j.note || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row between" style={{ marginTop: 16 }}>
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
      <PageHeader title="Push job" subtitle={job ? `${job.steps[0].device_name} · ${formatDate(job.created_at)}` : 'Loading…'}>
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
