import { useMemo, useState } from 'react'
import { Ban, CheckCircle2, Circle, CircleX, Loader2, ThumbsDown, ThumbsUp } from 'lucide-react'
import { post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { KIND, NOTE_HINT, NOTE_PATTERN, canCancel, deviceNames, isRunning, isTerminal, phaseStates, statusLabel, statusTone } from '../lib/jobs.js'
import CodeBlock from './CodeBlock.jsx'
import RunForm from './RunForm.jsx'
import { Alert, Badge, ErrorNote, Field, Panel, formatDate } from './ui.jsx'

const PHASE_ICON = { done: CheckCircle2, active: Loader2, failed: CircleX, pending: Circle }

export function StatusBadge({ status }) {
  return <Badge tone={statusTone(status)} dot={isRunning(status)}>{statusLabel(status)}</Badge>
}

export function JobProgress({ job, index = 0 }) {
  const phases = phaseStates(job, index)
  const step = job.steps[index]
  const status = step.status
  const rolling = step.timeline.some((t) => t.state === 'rolling_back')
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
        <li className={status === 'rolling_back' ? 'active' : status === 'rolled_back' ? 'done' : 'failed'}>
          {status === 'rolling_back' ? <Loader2 size={18} aria-hidden="true" className="spin" /> : status === 'rolled_back' ? <CheckCircle2 size={18} aria-hidden="true" /> : <CircleX size={18} aria-hidden="true" />}
          <span>Roll back to the previous configuration</span>
        </li>
      )}
    </ol>
  )
}

function Outcome({ job, step }) {
  const err = step.error
  const status = step.status
  if (status === 'success') {
    return <Alert tone="success" title="Done.">The change was applied, verified{job.plan?.save === false ? '' : ' and saved'}.</Alert>
  }
  if (!err && !['failed', 'blocked', 'rolled_back'].includes(status)) return null
  const title = { blocked: 'Blocked – nothing was sent.', rolled_back: 'Rolled back – the device is back on its previous configuration.', failed: 'Failed.' }[status] || 'Problem.'
  return (
    <Alert tone={status === 'rolled_back' ? 'warning' : 'danger'} title={title}>
      {err?.message}
      {err?.command && <> <br />Command: <code>{err.command}</code></>}
    </Alert>
  )
}

/** Verification or link checks: {name, ok, detail, required}. */
export function Checks({ checks }) {
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
              <td>{c.name}{c.required === false && <span className="faint"> (info)</span>}</td>
              <td><Badge tone={c.ok ? 'success' : c.required === false ? 'warning' : 'danger'}>{c.ok ? 'pass' : 'fail'}</Badge></td>
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
        {job.steps.length > 1 ? 'A device in this job is' : 'This device is'} tagged production, so an admin other
        than {job.requested_by.username} must approve it before it can run. The request
        expires {formatDate(job.approval.expires_at)}.
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

/** Several devices: pick which one the panels below show. */
function StepPicker({ job, index, setIndex }) {
  return (
    <div className="choice-grid" role="group" aria-label="Devices in this job">
      {job.steps.map((s, i) => (
        <button type="button" key={`${s.device_id}-${i}`} className="choice" aria-pressed={i === index} onClick={() => setIndex(i)}>
          <strong>{s.role ? `${s.role} · ` : ''}{s.device_name}</strong>
          <small>{s.mgmt_ip || s.connection}</small>
          <StatusBadge status={s.status} />
        </button>
      ))}
    </div>
  )
}

/** Everything about one job: approval, credentials form, live progress, result, commands and output. */
export default function JobView({ job, setJob }) {
  const { user, can } = useAuth()
  const [error, setError] = useState(null)
  const [picked, setPicked] = useState(null)
  const many = job.steps.length > 1
  // Follow the device being changed until the user picks one.
  const index = picked ?? Math.max(0, job.steps.findIndex((s) => isRunning(s.status)))
  const step = job.steps[index] || job.steps[0]
  const mine = job.requested_by.id === user?.id || can('admin')
  const started = job.steps.some((s) => s.timeline.some((t) => t.state === 'queued'))
  const commands = step.commands_sent?.length ? step.commands_sent : step.commands || []
  const [backupOpen, setBackupOpen] = useState(false)
  const outputLines = useMemo(() => (step.output || '').split('\n'), [step.output])
  const backupLines = useMemo(() => (step.backup || '').split('\n'), [step.backup])
  const title = deviceNames(job, job.steps.length)

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
        title={title}
        subtitle={`${KIND[job.kind]} · requested by ${job.requested_by.username} · ${formatDate(job.created_at)}${job.approval?.approved_by ? ` · approved by ${job.approval.approved_by.username}` : ''}`}
        actions={
          <>
            <StatusBadge status={job.status} />
            {mine && can('engineer') && canCancel(job) && (
              <button type="button" className="btn small" onClick={cancel}>
                <Ban size={16} aria-hidden="true" /> {started ? (job.kind === 'multi' ? 'Stop the remaining switches' : 'Cancel') : 'Withdraw'}
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
          {job.status === 'cancelled' && !started && (
            <Alert tone="info">
              {job.cancel_reason === 'rejected' ? `Rejected by ${job.rejected_by?.username}${job.reject_note ? `: ${job.reject_note}` : '.'}` : 'Withdrawn by the requester. Nothing was sent to the device.'}
            </Alert>
          )}
          {job.status === 'expired' && <Alert tone="info">Not approved within 24 hours. Create a new job if it is still needed.</Alert>}
          {job.summary && <p className="muted" style={{ margin: 0 }}>{job.summary}</p>}
          {many && <StepPicker job={job} index={index} setIndex={setPicked} />}
          {many && <h3 style={{ margin: 0 }}>{step.role ? `Side ${step.role}: ` : ''}{step.device_name}</h3>}
          {step.timeline.some((t) => t.state === 'connecting') && <JobProgress job={job} index={index} />}
          {started && <Outcome job={job} step={step} />}
          {step.notes?.length > 0 && (
            <ul className="stack" style={{ margin: 0, paddingLeft: 'var(--space-5)' }} aria-label="Notes">
              {step.notes.map((n, i) => <li key={i} className={n.includes('MANUAL ACTION') ? 'text-danger' : 'muted'}>{n}</li>)}
            </ul>
          )}
          <ErrorNote error={error} />
        </div>
      </Panel>

      {job.link_checks?.length > 0 && (
        <Panel title="Both sides match" subtitle="Checked on the two plans before anything is sent.">
          <Checks checks={job.link_checks} />
        </Panel>
      )}

      {step.checks?.length > 0 && (
        <Panel title="Verification" subtitle={`${many ? `${step.device_name}: ` : ''}parsed from the show commands after applying.`}>
          <Checks checks={step.checks} />
        </Panel>
      )}

      <div className="grid two">
        <Panel title="Commands" subtitle={`${many ? `${step.device_name} · ` : ''}secrets masked.`}>
          <CodeBlock lines={commands} label={`${commands.length} configuration commands`} />
          {step.warnings?.length > 0 && step.warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
        </Panel>
        <Panel title="Device session" subtitle="Everything sent and received (masked).">
          {step.output ? (
            <details open={isRunning(step.status) || ['failed', 'rolled_back', 'blocked'].includes(step.status)}>
              <summary>Show the session transcript</summary>
              <CodeBlock lines={outputLines} label="Transcript" />
            </details>
          ) : (
            <p className="faint">{started ? (isTerminal(step.status) ? 'Not started on this device.' : 'Waiting for the device…') : 'Nothing has been sent yet.'}</p>
          )}
          {step.backup && (
            <details onToggle={(e) => setBackupOpen(e.currentTarget.open)}>
              <summary>Show the backup taken before the change ({backupLines.length} lines)</summary>
              {/* A running config has thousands of lines: rendered only while open, not on every poll. */}
              {backupOpen && <CodeBlock lines={backupLines} label="Running config backup (masked)" />}
            </details>
          )}
        </Panel>
      </div>
    </div>
  )
}
