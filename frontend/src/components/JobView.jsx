import { useState } from 'react'
import { Ban, CheckCircle2, Circle, CircleX, Loader2, ThumbsDown, ThumbsUp } from 'lucide-react'
import { post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { CANCELLABLE, NOTE_HINT, NOTE_PATTERN, isRunning, phaseStates, statusLabel, statusTone } from '../lib/jobs.js'
import CodeBlock from './CodeBlock.jsx'
import RunForm from './RunForm.jsx'
import { Alert, Badge, ErrorNote, Field, Panel, formatDate } from './ui.jsx'

const PHASE_ICON = { done: CheckCircle2, active: Loader2, failed: CircleX, pending: Circle }

export function StatusBadge({ status }) {
  return <Badge tone={statusTone(status)} dot={isRunning(status)}>{statusLabel(status)}</Badge>
}

export function JobProgress({ job }) {
  const phases = phaseStates(job)
  const rolling = job.steps[0].timeline.some((t) => t.state === 'rolling_back')
  return (
    <ol className="progress-list" aria-label="Push progress">
      {phases.map(({ id, label, state }) => {
        const Icon = PHASE_ICON[state]
        return (
          <li key={id} className={state}>
            <Icon size={18} aria-hidden="true" className={state === 'active' ? 'spin' : undefined} />
            <span>{label}</span>
            <span className="sr-only"> – {state}</span>
          </li>
        )
      })}
      {rolling && (
        <li className={job.status === 'rolling_back' ? 'active' : job.status === 'rolled_back' ? 'done' : 'failed'}>
          {job.status === 'rolling_back' ? <Loader2 size={18} aria-hidden="true" className="spin" /> : job.status === 'rolled_back' ? <CheckCircle2 size={18} aria-hidden="true" /> : <CircleX size={18} aria-hidden="true" />}
          <span>Roll back to the previous configuration</span>
        </li>
      )}
    </ol>
  )
}

function Outcome({ job }) {
  const step = job.steps[0]
  const err = step.error
  if (job.status === 'success') {
    return <Alert tone="success" title="Done.">The change was applied, verified{job.plan?.save === false ? '' : ' and saved'}.</Alert>
  }
  if (!err && !['failed', 'blocked', 'rolled_back'].includes(job.status)) return null
  const title = { blocked: 'Blocked – nothing was sent.', rolled_back: 'Rolled back.', failed: 'Failed.' }[job.status] || 'Problem.'
  return (
    <Alert tone={job.status === 'rolled_back' ? 'warning' : 'danger'} title={title}>
      {err?.message}
      {err?.command && <> <br />Command: <code>{err.command}</code></>}
    </Alert>
  )
}

function Checks({ checks }) {
  if (!checks?.length) return null
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Detail</th></tr>
        </thead>
        <tbody>
          {checks.map((c, i) => (
            <tr key={i}>
              <td>{c.name}{!c.required && <span className="faint"> (info)</span>}</td>
              <td><Badge tone={c.ok ? 'success' : c.required ? 'danger' : 'warning'}>{c.ok ? 'pass' : 'fail'}</Badge></td>
              <td className="faint">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Approval({ job, setJob }) {
  const { user, can } = useAuth()
  const [reason, setReason] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const own = job.requested_by.id === user?.id
  const badReason = !NOTE_PATTERN.test(reason)

  async function act(action) {
    setBusy(true)
    setError(null)
    try {
      setJob(await post(`/jobs/${job.id}/${action}`, action === 'reject' ? { reason } : {}))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <Alert tone="warning" title="Waiting for a second person.">
        This device is tagged production, so an admin other than {job.requested_by.username} must approve it before
        it can run. The request expires {formatDate(job.approval.expires_at)}.
      </Alert>
      {can('admin') && !own && (
        <div className="stack">
          <Field label="Reason (shown to the requester if you reject)" error={badReason ? NOTE_HINT : null}>
            {(props) => <input {...props} className="input" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div className="row">
            <button type="button" className="btn primary" disabled={busy} onClick={() => act('approve')}>
              <ThumbsUp size={18} aria-hidden="true" /> Approve
            </button>
            <button type="button" className="btn danger" disabled={busy || badReason} onClick={() => act('reject')}>
              <ThumbsDown size={18} aria-hidden="true" /> Reject
            </button>
          </div>
        </div>
      )}
      {can('admin') && own && <p className="faint">You requested this change, so another admin has to approve it.</p>}
      <ErrorNote error={error} />
    </div>
  )
}

/** Everything about one job: approval, credentials form, live progress, result, commands and output. */
export default function JobView({ job, setJob }) {
  const { user, can } = useAuth()
  const [error, setError] = useState(null)
  const step = job.steps[0]
  const mine = job.requested_by.id === user?.id || can('admin')
  const started = step.timeline.some((t) => t.state === 'queued')
  const commands = step.commands_sent?.length ? step.commands_sent : step.commands || []

  async function cancel() {
    setError(null)
    try {
      setJob(await post(`/jobs/${job.id}/cancel`))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="stack">
      <Panel
        title={step.device_name}
        subtitle={`Requested by ${job.requested_by.username} · ${formatDate(job.created_at)}${job.approval?.approved_by ? ` · approved by ${job.approval.approved_by.username}` : ''}`}
        actions={
          <>
            <StatusBadge status={job.status} />
            {mine && can('engineer') && CANCELLABLE.includes(job.status) && (
              <button type="button" className="btn small" onClick={cancel}>
                <Ban size={16} aria-hidden="true" /> {started ? 'Cancel' : 'Withdraw'}
              </button>
            )}
          </>
        }
      >
        <div className="stack" aria-live="polite">
          {job.status === 'awaiting_approval' && <Approval job={job} setJob={setJob} />}
          {job.status === 'ready' && (mine && can('engineer') ? (
            <RunForm job={job} onStarted={setJob} />
          ) : (
            <Alert tone="info">Ready – waiting for {job.requested_by.username} to run it.</Alert>
          ))}
          {job.status === 'cancelled' && (
            <Alert tone="info">
              {job.cancel_reason === 'rejected' ? `Rejected by ${job.rejected_by?.username}${job.reject_note ? `: ${job.reject_note}` : '.'}` : 'Withdrawn by the requester. Nothing was sent to the device.'}
            </Alert>
          )}
          {job.status === 'expired' && <Alert tone="info">Not approved within 24 hours. Create a new job if it is still needed.</Alert>}
          {started && <JobProgress job={job} />}
          <Outcome job={job} />
          {step.notes?.length > 0 && (
            <ul className="stack" style={{ margin: 0, paddingLeft: 'var(--space-5)' }} aria-label="Notes">
              {step.notes.map((n, i) => <li key={i} className={n.includes('MANUAL ACTION') ? 'text-danger' : 'muted'}>{n}</li>)}
            </ul>
          )}
          <ErrorNote error={error} />
        </div>
      </Panel>

      {step.checks?.length > 0 && (
        <Panel title="Verification" subtitle="Parsed from the show commands after applying.">
          <Checks checks={step.checks} />
        </Panel>
      )}

      <div className="grid two">
        <Panel title="Commands" subtitle="Secrets masked.">
          <CodeBlock lines={commands} label={`${commands.length} configuration commands`} />
          {step.warnings?.length > 0 && step.warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
        </Panel>
        <Panel title="Device session" subtitle="Everything sent and received (masked).">
          {step.output ? (
            <details open={isRunning(job.status) || ['failed', 'rolled_back', 'blocked'].includes(job.status)}>
              <summary>Show the session transcript</summary>
              <CodeBlock lines={step.output.split('\n')} label="Transcript" />
            </details>
          ) : (
            <p className="faint">{started ? 'Waiting for the device…' : 'Nothing has been sent yet.'}</p>
          )}
          {step.backup && (
            <details>
              <summary>Show the backup taken before the change ({step.backup.split('\n').length} lines)</summary>
              <CodeBlock lines={step.backup.split('\n')} label="Running config backup (masked)" />
            </details>
          )}
        </Panel>
      </div>
    </div>
  )
}
