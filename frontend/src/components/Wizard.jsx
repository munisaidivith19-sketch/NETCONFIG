import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Cable, ClipboardCheck, History, PlugZap, Send, SlidersHorizontal } from 'lucide-react'
import { get, post } from '../lib/api.js'
import { NOTE_HINT, NOTE_PATTERN } from '../lib/jobs.js'
import { useJob } from '../lib/useJob.js'
import CodeBlock from './CodeBlock.jsx'
import JobView from './JobView.jsx'
import { Alert, Badge, Empty, ErrorNote, Field, Panel } from './ui.jsx'

// Building blocks shared by the Configure pages that create multi-step jobs (several switches, router link,
// first-time setup). They all call POST /jobs/preview, then POST /jobs; the backend builds and checks the
// commands for every device (backend/app/services/wizards.py).

const TABS = [
  { to: '/configure', label: 'Device change', icon: SlidersHorizontal, end: true },
  { to: '/configure/link', label: 'Router link', icon: Cable },
  { to: '/configure/bootstrap', label: 'First-time setup', icon: PlugZap },
]

export function ConfigureTabs() {
  return (
    <nav aria-label="Kind of change" className="subnav glass">
      {TABS.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className="subnav-link">
          <Icon size={18} aria-hidden="true" /> <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

/** Field errors from the preview / create response, as a list with the field path. */
export function ErrorList({ errors, label = 'to fix' }) {
  const list = Object.entries(errors || {})
  if (!list.length) return null
  return (
    <Alert tone="danger" title={`${list.length} problem${list.length > 1 ? 's' : ''} ${label}.`}>
      <ul style={{ margin: 0, paddingLeft: 'var(--space-5)' }}>
        {list.map(([path, msg]) => <li key={path}><code>{path}</code>: {msg}</li>)}
      </ul>
    </Alert>
  )
}

/** The response of POST /jobs/preview: per-device commands, link checks, warnings. */
export function JobPreview({ preview }) {
  if (!preview) return null
  const { steps = [], checks = [], warnings = [] } = preview
  const same = steps.length > 1 && steps.every((s) => s.commands.join('\n') === steps[0].commands.join('\n'))
  const shown = same ? [steps[0]] : steps
  return (
    <div className="stack">
      <ErrorList errors={preview.errors} />
      {checks.length > 0 && (
        <Panel title="Both sides match" subtitle="Read back from the two generated plans.">
          <ul className="progress-list">
            {checks.map((c) => (
              <li key={c.name} className={c.ok ? 'done' : 'failed'}>
                <Badge tone={c.ok ? 'success' : 'danger'}>{c.ok ? 'pass' : 'fail'}</Badge>
                <span>{c.name}{c.detail ? <span className="faint"> · {c.detail}</span> : null}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      {preview.ok && (
        <div className="grid two">
          {shown.map((s) => (
            <Panel key={s.device_id} title={same ? `Every switch (${steps.length})` : `${s.role ? `${s.role} · ` : ''}${s.device_name}`}
              subtitle={same ? steps.map((x) => x.device_name).join(', ') : `Rollback after ${s.revert_minutes} min unless confirmed`}>
              {s.commands.length ? (
                <CodeBlock lines={s.commands} label={`${s.commands.length} configuration commands (secrets masked)`} />
              ) : (
                <Empty icon={ClipboardCheck} title="Nothing to send">Add at least one requirement.</Empty>
              )}
              {s.verify_commands.length > 0 && <CodeBlock lines={s.verify_commands} label="Verification" />}
            </Panel>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <Panel title="Warnings">
          <div className="stack">{warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}</div>
        </Panel>
      )}
    </div>
  )
}

/**
 * State shared by the wizard pages: the device list, the POST /jobs/preview call and the created job
 * (kept fresh by useJob). A 422 with field errors becomes a failed preview, so the form can mark the fields.
 */
export function useJobWizard() {
  const [devices, setDevices] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [jobId, setJobId] = useState(null)
  const { job, setJob } = useJob(jobId)

  useEffect(() => {
    const ctrl = new AbortController()
    get('/devices', { query: { page_size: 200 }, signal: ctrl.signal })
      .then((r) => setDevices(r.items))
      .catch((err) => err.name !== 'AbortError' && setLoadError(err))
    return () => ctrl.abort()
  }, [])

  async function runPreview(body) {
    setLoading(true)
    setPreviewError(null)
    try {
      setPreview(await post('/jobs/preview', body))
    } catch (err) {
      if (err.status === 422 && Object.keys(err.fields).length) setPreview({ ok: false, errors: err.fields, steps: [] })
      else setPreviewError(err)
    } finally {
      setLoading(false)
    }
  }

  return {
    devices, loadError, preview, setPreview, previewError, loading, runPreview, job, setJob,
    onCreated: (j) => { setJob(j); setJobId(j.id) },
    reset: () => { setJobId(null); setJob(null); setPreview(null) },
  }
}

/** A created job: live progress, a link to History and a button to start over. */
export function FinishedJob({ job, setJob, again, onAgain }) {
  return (
    <>
      <JobView job={job} setJob={setJob} />
      <div className="form-actions">
        <Link className="btn" to={`/history/${job.id}`}><History size={18} aria-hidden="true" /> Open in History</Link>
        <button type="button" className="btn primary" onClick={onAgain}>{again}</button>
      </div>
    </>
  )
}

/** Create the job from the previewed request. Credentials are asked for later, when it runs. */
export function CreateJob({ body, production, onCreated, what = 'this change', children }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const badNote = !NOTE_PATTERN.test(note)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      onCreated(await post('/jobs', { ...body, note }))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Create the job" subtitle="The job freezes these exact commands. Credentials are asked for only when it runs.">
      <div className="stack">
        {production ? (
          <Alert tone="warning" title="Production device.">
            A second user (an admin) must approve {what} before it can run. The request expires after 24 hours.
          </Alert>
        ) : (
          <Alert tone="info">No device here is tagged production, so no second approval is needed: you can run it next.</Alert>
        )}
        {children}
        <Field label="Change note (optional)" hint="Why this change? Shown in History and to the approver." error={badNote ? NOTE_HINT : null}>
          {(props) => <input {...props} className="input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <ErrorNote error={error} />
        {Object.keys(error?.fields || {}).length > 0 && <ErrorList errors={error.fields} />}
        <div className="form-actions">
          <button type="button" className="btn primary" disabled={busy || badNote} onClick={create}>
            <Send size={18} aria-hidden="true" /> {busy ? 'Creating…' : production ? 'Request approval' : 'Create job'}
          </button>
        </div>
      </div>
    </Panel>
  )
}

/** Shared input with a label, hint and error (the backend's field path decides which error shows). */
export function TextInput({ label, value, onChange, error, hint, placeholder, mono, inputMode, maxLength = 80 }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(props) => (
        <input {...props} className="input" value={value} placeholder={placeholder} inputMode={inputMode} maxLength={maxLength}
          style={mono ? { fontFamily: 'var(--font-mono)' } : undefined} autoComplete="off" spellCheck={false}
          onChange={(e) => onChange(e.target.value)} />
      )}
    </Field>
  )
}

export function SelectInput({ label, value, onChange, options, error, hint }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(props) => (
        <select {...props} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
        </select>
      )}
    </Field>
  )
}
