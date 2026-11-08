import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Boxes, CheckCircle2, ClipboardCheck, History, KeyRound, Send, Server, ShieldCheck } from 'lucide-react'
import CodeBlock from '../components/CodeBlock.jsx'
import JobView from '../components/JobView.jsx'
import PlanForm from '../components/PlanForm.jsx'
import { Alert, Badge, Empty, ErrorNote, Field, PageHeader, Panel, SkeletonRows } from '../components/ui.jsx'
import { get, post } from '../lib/api.js'
import { NOTE_HINT, NOTE_PATTERN } from '../lib/jobs.js'
import { useJob } from '../lib/useJob.js'
import { SUPPORT, categoryIcon, categoryLabel } from '../lib/labels.js'
import { emptyForm, normalizeErrors, sectionOf, toPlan } from '../lib/plan.js'

const STEPS = ['Device', 'Requirements', 'Preview', 'Approval', 'Push & verify']

function Steps({ step, setStep, allowed }) {
  return (
    <nav aria-label="Configuration steps">
      <ol className="steps glass">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? 'step' : undefined} className={i < step ? 'done' : undefined}>
            <button type="button" onClick={() => setStep(i)} disabled={!allowed(i)}>
              <span className="num" aria-hidden="true">{i + 1}</span>
              <span className="step-label">{label}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}

function DeviceStep({ target, setTarget }) {
  const [mode, setMode] = useState(target?.kind || 'device')
  const [devices, setDevices] = useState(null)
  const [models, setModels] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    const req = mode === 'device'
      ? get('/devices', { query: { page_size: 200 }, signal: ctrl.signal }).then((r) => setDevices(r.items))
      : get('/catalog/models', { query: { page_size: 200 }, signal: ctrl.signal }).then((r) => setModels(r.items))
    req.catch((err) => err.name !== 'AbortError' && setError(err))
    return () => ctrl.abort()
  }, [mode])

  async function pick(kind, item) {
    setError(null)
    try {
      const modelId = kind === 'device' ? item.model_id : item.id
      const model = await get(`/catalog/models/${modelId}`)
      setTarget({
        kind,
        id: item.id,
        name: kind === 'device' ? item.name : model.name,
        model,
        capabilities: new Set(kind === 'device' ? item.capabilities : model.capabilities),
        production: kind === 'device' ? item.production : false,
        support: model.os_driver?.support,
        os: model.os_driver?.name,
        device: kind === 'device' ? item : null,
      })
    } catch (err) {
      setError(err)
    }
  }

  const list = mode === 'device' ? devices : models
  return (
    <Panel title="Choose the target" subtitle="An inventory device, or just a catalog model to see the commands it would get.">
      <div className="row" role="group" aria-label="Target type" style={{ marginBottom: 'var(--space-4)' }}>
        <button type="button" className={`btn ${mode === 'device' ? 'primary' : ''}`} aria-pressed={mode === 'device'} onClick={() => setMode('device')}>
          <Server size={18} aria-hidden="true" /> Inventory device
        </button>
        <button type="button" className={`btn ${mode === 'model' ? 'primary' : ''}`} aria-pressed={mode === 'model'} onClick={() => setMode('model')}>
          <Boxes size={18} aria-hidden="true" /> Catalog model (preview only)
        </button>
      </div>
      <ErrorNote error={error} />
      {!list && !error && <SkeletonRows rows={3} />}
      {list && list.length === 0 && (
        <Empty icon={Server} title={mode === 'device' ? 'No devices yet' : 'The catalog is empty'}
          action={mode === 'device' ? <Link className="btn primary" to="/devices">Add a device</Link> : null}>
          {mode === 'device' ? 'Add the device to the inventory first, or preview against a catalog model.' : 'Run scripts/seed_catalog.py.'}
        </Empty>
      )}
      {list && list.length > 0 && (
        <div className="choice-grid">
          {list.map((item) => {
            const Icon = categoryIcon(item.category)
            const chosen = target?.kind === mode && target.id === item.id
            const support = SUPPORT[item.support] || null
            return (
              <button type="button" key={item.id} className="choice" aria-pressed={chosen} onClick={() => pick(mode, item)}>
                <Icon size={22} aria-hidden="true" />
                <strong>{item.name}</strong>
                <small>
                  {mode === 'device' ? `${item.model_name || item.model_id} · ${item.mgmt_ip || 'no IP'}` : `${item.brand || ''} · ${categoryLabel(item.category)}`}
                </small>
                <span className="row">
                  {mode === 'device' && item.production && <Badge tone="danger">production</Badge>}
                  {support && <Badge tone={support.tone}>{support.label}</Badge>}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

function PreviewStep({ preview, error, loading, onRetry, goFix }) {
  if (loading) return <Panel title="Preview"><SkeletonRows rows={6} /></Panel>
  if (error) return <Panel title="Preview"><ErrorNote error={error} /><button type="button" className="btn" onClick={onRetry}>Try again</button></Panel>
  if (!preview) return null
  const errorList = Object.entries(preview.errors)
  return (
    <div className="grid two">
      <Panel title="Commands" subtitle={`${preview.driver.name} · nothing has been sent to a device`}>
        {errorList.length > 0 ? (
          <div className="stack">
            <Alert tone="danger" title={`${errorList.length} problem${errorList.length > 1 ? 's' : ''} to fix.`}>No commands were generated.</Alert>
            <ul className="stack" style={{ margin: 0, paddingLeft: 'var(--space-5)' }}>
              {errorList.map(([path, msg]) => (
                <li key={path}>
                  <code>{path}</code>: {msg}{' '}
                  <button type="button" className="btn small ghost" onClick={() => goFix(path)}>Fix</button>
                </li>
              ))}
            </ul>
          </div>
        ) : preview.commands.length === 0 ? (
          <Empty icon={ClipboardCheck} title="Nothing to send">Add at least one requirement.</Empty>
        ) : (
          <CodeBlock lines={preview.commands} label={`${preview.commands.length} configuration commands (secrets masked)`} />
        )}
      </Panel>
      <div className="stack">
        {preview.warnings.length > 0 && (
          <Panel title="Warnings">
            <div className="stack">
              {preview.warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
            </div>
          </Panel>
        )}
        {preview.ok && (
          <Panel title="How it will be applied">
            <ul className="progress-list">
              <li><ShieldCheck size={18} aria-hidden="true" /> Rollback: {preview.rollback === 'revert_timer' ? `automatic after ${preview.revert_minutes} min unless confirmed` : preview.rollback}</li>
              <li><ClipboardCheck size={18} aria-hidden="true" /> {preview.verify_commands.length} verification commands</li>
              <li><KeyRound size={18} aria-hidden="true" /> {preview.save_command ? `Saved with "${preview.save_command}"` : 'Not saved to startup configuration'}</li>
            </ul>
            {preview.verify_commands.length > 0 && <CodeBlock lines={preview.verify_commands} label="Verification" />}
            <p className="faint">Commands hash <code>{preview.commands_hash.slice(0, 16)}…</code></p>
          </Panel>
        )}
      </div>
    </div>
  )
}

function CreateJob({ target, plan, onCreated }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const badNote = !NOTE_PATTERN.test(note)

  async function create() {
    setBusy(true)
    setError(null)
    try {
      onCreated(await post('/jobs', { device_id: target.id, plan, note }))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Create the push job" subtitle="The job freezes these exact commands. Credentials are asked for only when it runs.">
      <div className="stack">
        {target.production ? (
          <Alert tone="warning" title="Production device.">
            A second user (an admin) must approve this change before it can run. The request expires after 24 hours.
          </Alert>
        ) : (
          <Alert tone="info">This device is not tagged production, so no second approval is needed: you can run it next.</Alert>
        )}
        <Field label="Change note (optional)" hint="Why this change? Shown in History and to the approver." error={badNote ? NOTE_HINT : null}>
          {(props) => <input {...props} className="input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <ErrorNote error={error} />
        <div className="form-actions">
          <button type="button" className="btn primary" disabled={busy || badNote} onClick={create}>
            <Send size={18} aria-hidden="true" /> {busy ? 'Creating…' : target.production ? 'Request approval' : 'Create job'}
          </button>
        </div>
      </div>
    </Panel>
  )
}

export default function Configure() {
  const [params] = useSearchParams()
  const [step, setStep] = useState(0)
  const [target, setTarget] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [errors, setErrors] = useState({})
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [jobId, setJobId] = useState(null)
  const { job, setJob } = useJob(jobId)
  const started = Boolean(job?.steps?.[0]?.timeline?.some((t) => t.state === 'queued'))

  // Once the run starts, move on to the live progress step.
  useEffect(() => {
    if (started) setStep(4)
  }, [started])

  // /configure?device=<id> preselects a device (link from the Devices page).
  const wanted = params.get('device')
  useEffect(() => {
    if (!wanted || target) return
    get(`/devices/${wanted}`)
      .then(async (d) => {
        const model = await get(`/catalog/models/${d.model_id}`)
        setTarget({ kind: 'device', id: d.id, name: d.name, model, capabilities: new Set(d.capabilities), production: d.production, support: model.os_driver?.support, os: model.os_driver?.name, device: d })
        setStep(1)
      })
      .catch(() => {})
  }, [wanted, target])

  const portHint = useMemo(() => {
    const ex = target?.model?.port_examples || []
    return ex.length ? `Ports on this model look like ${ex.slice(0, 2).join(', ')}; short names such as Gi1/0/1 work too.` : ''
  }, [target])

  function resetJob() {
    setJobId(null)
    setJob(null)
  }

  function chooseTarget(t) {
    setTarget(t)
    resetJob()
    setPreview(null)
    setErrors({})
    setStep(1)
  }

  async function runPreview() {
    if (job && started) resetJob() // starting a new change after a finished push
    setStep(2)
    setLoading(true)
    setPreviewError(null)
    try {
      const body = { plan: toPlan(form), [target.kind === 'device' ? 'device_id' : 'model_id']: target.id }
      const res = await post('/plans/preview', body)
      setPreview(res)
      setErrors(res.errors)
    } catch (err) {
      if (err.status === 422 && Object.keys(err.fields).length) {
        const fields = normalizeErrors(err.fields)
        setErrors(fields)
        setPreview({ ok: false, errors: fields, warnings: [], commands: [], verify_commands: [], driver: { name: target.os } })
      } else {
        setPreviewError(err)
        setPreview(null)
      }
    } finally {
      setLoading(false)
    }
  }

  function goFix(path) {
    setStep(1)
    requestAnimationFrame(() => document.getElementById(`sec-${sectionOf(path)}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }))
  }

  const updateForm = (fn) => {
    setForm(fn)
    if (preview?.ok) setPreview(null) // the preview no longer matches the form
    if (job && !started) resetJob() // a job not yet run belongs to the old plan; History still has it
  }

  const allowed = (i) =>
    i === 0 || (i <= 2 && Boolean(target)) || (i === 3 && Boolean(preview?.ok) && target?.kind === 'device') || (i === 4 && started)

  return (
    <>
      <PageHeader title="Configure" subtitle="Requirements → validated commands → safe push with automatic rollback.">
        {target && (
          <span className="row">
            <Badge tone="info">{target.name}</Badge>
            {target.production && <Badge tone="danger">production</Badge>}
            {SUPPORT[target.support] && <Badge tone={SUPPORT[target.support].tone}>{SUPPORT[target.support].label}</Badge>}
          </span>
        )}
      </PageHeader>
      <div className="stack">
        <Steps step={step} setStep={(i) => (i === 2 ? runPreview() : setStep(i))} allowed={allowed} />

        {step === 0 && <DeviceStep target={target} setTarget={chooseTarget} />}

        {step === 1 && target && (
          <Panel title="Requirements" subtitle={`${target.model.name} · ${target.os || 'no driver'}`}
            actions={<button type="button" className="btn primary" onClick={runPreview}>Preview commands</button>}>
            {target.support === 'experimental' && (
              <Alert tone="warning">The {target.os} driver is experimental: check the preview carefully and test in a lab first.</Alert>
            )}
            {Object.keys(errors).length > 0 && <Alert tone="danger">Some fields need attention; they are marked below.</Alert>}
            <PlanForm form={form} setForm={updateForm} caps={target.capabilities} errors={errors} production={target.production} portHint={portHint} />
            <div className="form-actions">
              <button type="button" className="btn" onClick={() => setStep(0)}>Back</button>
              <button type="button" className="btn primary" onClick={runPreview}>Preview commands</button>
            </div>
          </Panel>
        )}

        {step === 2 && (
          <>
            <PreviewStep preview={preview} error={previewError} loading={loading} onRetry={runPreview} goFix={goFix} />
            <div className="form-actions">
              <button type="button" className="btn" onClick={() => setStep(1)}>Edit requirements</button>
              <button type="button" className="btn primary" disabled={!preview?.ok || target?.kind !== 'device'} onClick={() => setStep(3)}>
                <CheckCircle2 size={18} aria-hidden="true" /> Continue
              </button>
            </div>
            {preview?.ok && target?.kind !== 'device' && (
              <Alert tone="info">This was a catalog preview. Add the device to the inventory to push it.</Alert>
            )}
          </>
        )}

        {step === 3 && target && (job ? (
          <JobView job={job} setJob={setJob} />
        ) : (
          <CreateJob target={target} plan={toPlan(form)} onCreated={(j) => { setJob(j); setJobId(j.id) }} />
        ))}
        {step === 4 && job && (
          <>
            <JobView job={job} setJob={setJob} />
            <div className="form-actions">
              <Link className="btn" to={`/history/${job.id}`}><History size={18} aria-hidden="true" /> Open in History</Link>
              <button type="button" className="btn primary" onClick={() => { resetJob(); setPreview(null); setStep(1) }}>New change for this device</button>
            </div>
          </>
        )}
      </div>
    </>
  )
}
