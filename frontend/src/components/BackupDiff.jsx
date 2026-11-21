import { useMemo, useState } from 'react'
import { GitCompare } from 'lucide-react'
import { get } from '../lib/api.js'
import { diffLines, unified } from '../lib/diff.js'
import CodeBlock from './CodeBlock.jsx'
import Explain from './Explain.jsx'
import { Alert, ErrorNote, formatDate } from './ui.jsx'

const LOOK_BACK = 5 // earlier jobs to open when the most recent ones have no backup (cancelled, blocked …)

const lineClass = (l) => (l.startsWith('+ ') ? 'add' : l.startsWith('- ') ? 'del' : '')

/** The newest earlier job on the same device that has a backup: {job, backup} or null. */
async function previousBackup(job, deviceId) {
  const list = await get('/jobs', { query: { device_id: deviceId, page_size: 25 } })
  const older = list.items.filter((j) => j.id !== job.id && j.created_at < job.created_at).slice(0, LOOK_BACK)
  for (const item of older) {
    const full = await get(`/jobs/${item.id}`)
    const step = full.steps.find((s) => s.device_id === deviceId && s.backup)
    if (step) return { job: full, backup: step.backup }
  }
  return null
}

/**
 * Compare this job's backup (the running config just before the change) with the previous backup of the same
 * device: what changed on the device between the two pushes, including changes made outside NetConfig Studio.
 * Both backups were masked by the backend before they were stored.
 */
export default function BackupDiff({ job, step }) {
  const [state, setState] = useState(null) // null | 'loading' | {prev} | {none: true}
  const [error, setError] = useState(null)

  async function compare() {
    setError(null)
    setState('loading')
    try {
      const prev = await previousBackup(job, step.device_id)
      setState(prev ? { prev } : { none: true })
    } catch (err) {
      setError(err)
      setState(null)
    }
  }

  const result = useMemo(() => {
    if (!state?.prev) return null
    const ops = diffLines(state.prev.backup.split('\n'), step.backup.split('\n'))
    return ops ? unified(ops) : { tooBig: true }
  }, [state, step.backup])

  return (
    <div className="stack">
      {!result && (
        <div className="row">
          <button type="button" className="btn small" onClick={compare} disabled={state === 'loading'}>
            <GitCompare size={16} aria-hidden="true" /> {state === 'loading' ? 'Looking for the previous backup…' : 'Compare with the previous backup'}
          </button>
        </div>
      )}
      {state?.none && <p className="faint">No earlier backup of this device was found.</p>}
      {result?.tooBig && <Alert tone="info">The two configurations differ in too many lines to show here.</Alert>}
      {result && !result.tooBig && (
        result.lines.length === 0 ? (
          <p className="faint">No differences since the backup of {formatDate(state.prev.job.created_at)}.</p>
        ) : (
          <>
            <CodeBlock lines={result.lines} lineClass={lineClass}
              label={`Changes since ${formatDate(state.prev.job.created_at)}: ${result.added} added, ${result.removed} removed`} />
            <Explain kind="diff" text={result.lines.join('\n')} />
          </>
        )
      )}
      <ErrorNote error={error} />
    </div>
  )
}
