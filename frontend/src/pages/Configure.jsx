import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Boxes, CheckCircle2, ClipboardCheck, KeyRound, Layers, Server, ShieldCheck } from 'lucide-react'
import CodeBlock from '../components/CodeBlock.jsx'
import JobView from '../components/JobView.jsx'
import PlanForm from '../components/PlanForm.jsx'
import TemplateBar from '../components/TemplateBar.jsx'
import { ConfigureTabs, CreateJob, FinishedJob, JobPreview } from '../components/Wizard.jsx'
import { Alert, Badge, Checkbox, Empty, ErrorNote, PageHeader, Panel, SkeletonRows } from '../components/ui.jsx'
import { get, post } from '../lib/api.js'
import { useJob } from '../lib/useJob.js'
import { SUPPORT, categoryIcon, categoryLabel } from '../lib/labels.js'
import { NEW_ROWS, emptyForm, normalizeErrors, sectionOf, toPlan } from '../lib/plan.js'
import { reveal } from '../lib/scroll.js'

const SWITCHES = ['switch', 'l3switch']
const MAX_SWITCHES = 20

/** Multi-device errors are "steps.<i>.<plan path>" or "plan.<path>"; the form wants the plan path. */
function multiErrors(errors) {
  const out = {}
  for (const [k, v] of Object.entries(errors || {})) out[k.replace(/^steps\.\d+\./, '').replace(/^plan\./, '')] ??= v
  return out
}

const TARGET_TYPES = [
  { id: 'device', label: 'Inventory device', icon: Server },
  { id: 'multi', label: 'Several switches', icon: Layers },
  { id: 'model', label: 'Catalog model (preview only)', icon: Boxes },
]

const STEPS = ['Device', 'Requirements', 'Preview', 'Create job', 'Push & verify']

function Steps({ step, setStep, allowed }) {
  return (
    <nav aria-label="Configuration steps">
      <ol className="steps glass">
        {STEPS.map((label, i) => (
          <li key={label} className={i < step ? 'done' : undefined}>
            <button type="button" onClick={() => setStep(i)} disabled={!allowed(i)} aria-current={i === step ? 'step' : undefined}>
              <span className="num" aria-hidden="true">{i + 1}</span>
              <span className="step-label">{label}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}

function MultiPicker({ devices, target, setTarget, setError }) {
  const switches = devices.filter((d) => SWITCHES.includes(d.category) && d.connection?.method !== 'none')
  const [ids, setIds] = useState(target?.kind === 'multi' ? target.ids : [])
  const toggle = (id) => setIds((old) => (old.includes(id) ? old.filter((x) => x !== id) : old.length < MAX_SWITCHES ? [...old, id] : old))

  async function next() {
    setError(null)
    try {
      const chosen = switches.filter((d) => ids.includes(d.id))
      const model = await get(`/catalog/models/${chosen[0].model_id}`)
      // Only what every chosen switch can do is offered in the form.
      const caps = chosen.map((d) => new Set(d.capabilities)).reduce((a, b) => new Set([...a].filter((c) => b.has(c))))
      setTarget({
        kind: 'multi', ids: chosen.map((d) => d.id), name: `${chosen.length} switches`, names: chosen.map((d) => d.name),
        model, capabilities: caps, production: chosen.some((d) => d.production),
        support: chosen.some((d) => d.support === 'experimental') ? 'experimental' : model.os_driver?.support,
        os: model.os_driver?.name, device: null,
      })
    } catch (err) {
      setError(err)
    }
  }

  if (switches.length < 2) {
    return <Empty icon={Layers} title="Two switches needed">Add at least two switches with a connection method to the inventory.</Empty>
  }
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }}>
        The same VLANs and port settings go to every switch you pick, one switch after another. Per-device settings
        (hostname, IP addresses, routing) are configured one device at a time.
      </p>
      <div className="choice-grid" role="group" aria-label="Switches">
        {switches.map((d) => (
          <button type="button" key={d.id} className="choice" aria-pressed={ids.includes(d.id)} onClick={() => toggle(d.id)}>
            <Server size={22} aria-hidden="true" />
            <strong>{d.name}</strong>
            <small>{d.model_name || d.model_id} · {d.mgmt_ip || 'no IP'}</small>
            {d.production && <Badge tone="warning">production</Badge>}
          </button>
        ))}
      </div>
      <div className="form-actions">
        <span className="faint">{ids.length} selected (2–{MAX_SWITCHES})</span>
        <button type="button" className="btn primary" disabled={ids.length < 2} onClick={next}>
          Continue with {ids.length} switches
        </button>
      </div>
    </div>
  )
}

function DeviceStep({ target, setTarget }) {
  const [mode, setMode] = useState(target?.kind || 'device')
  const [devices, setDevices] = useState(null)
  const [models, setModels] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const ctrl = new AbortController()
    const req = mode !== 'model'
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

  const list = mode === 'model' ? models : devices
  return (
    <Panel title="Choose the target" subtitle="An inventory device, several switches at once, or just a catalog model to see the commands it would get.">
      {/* A segmented control, not three primary buttons: the only primary action on this step is picking a target. */}
      <div className="segmented" role="group" aria-label="Target type">
        {TARGET_TYPES.map(({ id, label, icon: Icon }) => (
          <button type="button" key={id} className="subnav-link" aria-pressed={mode === id} onClick={() => setMode(id)}>
            <Icon size={18} aria-hidden="true" /> {label}
          </button>
        ))}
      </div>
      <ErrorNote error={error} />
      {!list && !error && <SkeletonRows rows={3} />}
      {mode === 'multi' && devices && <MultiPicker devices={devices} target={target} setTarget={setTarget} setError={setError} />}
      {mode !== 'multi' && list && list.length === 0 && (
        <Empty icon={Server} title={mode === 'device' ? 'No devices yet' : 'The catalog is empty'}
          action={mode === 'device' ? <Link className="btn primary" to="/devices">Add a device</Link> : null}>
          {mode === 'device' ? 'Add the device to the inventory first, or preview against a catalog model.' : 'Run scripts/seed_catalog.py.'}
        </Empty>
      )}
      {mode !== 'multi' && list && list.length > 0 && (
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
                  {mode === 'device' && item.production && <Badge tone="warning">production</Badge>}
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

function PreviewStep({ preview, multi, error, loading, onRetry, goFix }) {
  if (loading) return <Panel title="Preview"><SkeletonRows rows={6} /></Panel>
  if (error) return <Panel title="Preview"><ErrorNote error={error} /><button type="button" className="btn" onClick={onRetry}>Try again</button></Panel>
  if (!preview) return null
  if (multi) return <JobPreview preview={preview} />
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

/** Configure's create step: the shared CreateJob, plus "stop on failure" for several switches. */
function CreateChange({ target, plan, onCreated }) {
  const [stopOnFailure, setStopOnFailure] = useState(true)
  const multi = target.kind === 'multi'
  const body = multi ? { device_ids: target.ids, plan, stop_on_failure: stopOnFailure } : { device_id: target.id, plan }
  return (
    <CreateJob body={body} production={target.production} onCreated={onCreated}>
      {multi && (
        <Checkbox label="Stop at the first switch that fails (recommended: a bad plan does not reach every switch)"
          checked={stopOnFailure} onChange={setStopOnFailure} />
      )}
    </CreateJob>
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
        // ...&port=<if>&for=<ap> (link from an access point or camera): start with an access port for that uplink.
        const port = params.get('port')
        if (port) {
          const forName = (params.get('for') || '').replace(/[^A-Za-z0-9._ -]/g, '').slice(0, 60)
          setForm((f) => ({ ...f, access: [{ ...NEW_ROWS.access(), interfaces: port, description: forName }] }))
        }
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
      if (target.kind === 'multi') {
        const res = await post('/jobs/preview', { device_ids: target.ids, plan: toPlan(form) })
        setPreview(res)
        setErrors(multiErrors(res.errors))
        return
      }
      const body = { plan: toPlan(form), [target.kind === 'device' ? 'device_id' : 'model_id']: target.id }
      const res = await post('/plans/preview', body)
      setPreview(res)
      setErrors(res.errors)
    } catch (err) {
      if (err.status === 422 && Object.keys(err.fields).length) {
        const fields = target.kind === 'multi' ? multiErrors(err.fields) : normalizeErrors(err.fields)
        setErrors(fields)
        setPreview({ ok: false, errors: fields, warnings: [], steps: [], commands: [], verify_commands: [], driver: { name: target.os } })
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
    requestAnimationFrame(() => reveal(document.getElementById(`sec-${sectionOf(path)}`)))
  }

  const updateForm = (fn) => {
    setForm(fn)
    if (preview?.ok) setPreview(null) // the preview no longer matches the form
    if (job && !started) resetJob() // a job not yet run belongs to the old plan; History still has it
  }

  // Focus management between steps: the button that was clicked usually disappears with the old step, which
  // would drop keyboard and screen-reader users at the top of the page. Move focus to the new step's first
  // heading instead (also once the preview has loaded, because the loading panel is replaced).
  const stepBox = useRef(null)
  const shownStep = useRef(step)
  useEffect(() => {
    const changed = shownStep.current !== step
    shownStep.current = step
    const lost = !document.activeElement || document.activeElement === document.body
    if (!changed && !lost) return
    const heading = stepBox.current?.querySelector('h2')
    if (!heading) return
    heading.tabIndex = -1
    heading.focus()
  }, [step, loading, job?.id])

  const pushable = target?.kind === 'device' || target?.kind === 'multi'
  const allowed = (i) =>
    i === 0 || (i <= 2 && Boolean(target)) || (i === 3 && Boolean(preview?.ok) && pushable) || (i === 4 && started)

  return (
    <>
      <PageHeader title="Configure" subtitle="Requirements → validated commands → safe push with automatic rollback.">
        {target && (
          <span className="row">
            <Badge tone="info">{target.kind === 'multi' ? target.names.join(', ') : target.name}</Badge>
            {target.production && <Badge tone="warning">production</Badge>}
            {SUPPORT[target.support] && <Badge tone={SUPPORT[target.support].tone}>{SUPPORT[target.support].label}</Badge>}
          </span>
        )}
      </PageHeader>
      <div className="stack">
        <ConfigureTabs />
        <Steps step={step} setStep={(i) => (i === 2 ? runPreview() : setStep(i))} allowed={allowed} />
        <div className="stack" ref={stepBox}>

          {step === 0 && <DeviceStep target={target} setTarget={chooseTarget} />}

          {step === 1 && target && (
            <Panel title="Requirements" subtitle={`${target.model.name} · ${target.os || 'no driver'}`}
              actions={<button type="button" className="btn primary" onClick={runPreview}>Preview commands</button>}>
              {target.support === 'experimental' && (
                <Alert tone="warning">The {target.os} driver is experimental: check the preview carefully and test in a lab first.</Alert>
              )}
              {Object.keys(errors).length > 0 && <Alert tone="danger">Some fields need attention; they are marked below.</Alert>}
              <TemplateBar form={form} setForm={updateForm} osId={target.model.os_driver?.id || target.model.os_id} />
              <PlanForm form={form} setForm={updateForm} caps={target.capabilities} errors={errors} production={target.production} portHint={portHint}
                category={target.kind === 'multi' ? null : target.model.category} />
              <div className="form-actions">
                <button type="button" className="btn" onClick={() => setStep(0)}>Back</button>
                <button type="button" className="btn primary" onClick={runPreview}>Preview commands</button>
              </div>
            </Panel>
          )}

          {step === 2 && (
            <>
              <PreviewStep preview={preview} multi={target?.kind === 'multi'} error={previewError} loading={loading} onRetry={runPreview} goFix={goFix} />
              <div className="form-actions">
                <button type="button" className="btn" onClick={() => setStep(1)}>Edit requirements</button>
                <button type="button" className="btn primary" disabled={!preview?.ok || !pushable} onClick={() => setStep(3)}>
                  <CheckCircle2 size={18} aria-hidden="true" /> Continue to create the job
                </button>
              </div>
              {preview?.ok && target?.kind === 'model' && (
                <Alert tone="info">This was a catalog preview. Add the device to the inventory to push it.</Alert>
              )}
            </>
          )}

          {step === 3 && target && (job ? (
            <JobView job={job} setJob={setJob} />
          ) : (
            <CreateChange target={target} plan={toPlan(form)} onCreated={(j) => { setJob(j); setJobId(j.id) }} />
          ))}
          {step === 4 && job && (
            <FinishedJob job={job} setJob={setJob} onAgain={() => { resetJob(); setPreview(null); setStep(1) }}
              again={target?.kind === 'multi' ? 'New change for these switches' : 'New change for this device'} />
          )}
        </div>
      </div>
    </>
  )
}
