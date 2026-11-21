import { useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { DRAFT_MAX, DRAFT_MIN, draftPlan, onlySupported, useAiStatus } from '../lib/ai.js'
import { useAuth } from '../lib/auth.jsx'
import { CAPABILITIES } from '../lib/labels.js'
import { fromPlan } from '../lib/plan.js'
import { Alert, ErrorNote, Field } from './ui.jsx'

const NAMES = { ...Object.fromEntries(CAPABILITIES), default_gateway: 'default gateway', ssh: 'an SSH login', custom_commands: 'custom commands' }
const name = (f) => NAMES[f] || f

/**
 * "Describe what you need": the assistant turns a sentence into a plan draft that pre-fills the form below. It is
 * only a draft: it never contains credentials or custom commands, it is previewed, checked for safety and (for
 * production) approved exactly like a plan typed by hand, and nothing here creates or runs a job.
 */
export default function AiDraft({ setForm, caps, category }) {
  const ai = useAiStatus()
  const { can } = useAuth()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  if (!ai?.enabled || !can('engineer')) return null
  const length = text.trim().length

  async function run() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const res = await draftPlan(text.trim())
      const { plan, removed } = onlySupported(res.plan, res.features, caps, category)
      setForm(() => fromPlan(plan))
      setResult({ ...res, removed, used: res.features.filter((f) => !removed.includes(f)) })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="section-card stack" aria-label="Describe what you need">
      <h3 style={{ margin: 0 }}>Describe what you need</h3>
      <Field label="Requirements in your own words"
        hint={`For example: "3 departments with 40 users each, Wi-Fi on VLAN 30, OSPF to the core". The draft replaces the form below. ${length}/${DRAFT_MAX}`}>
        {(props) => (
          <textarea {...props} className="textarea prose" rows={3} value={text} maxLength={DRAFT_MAX}
            onChange={(e) => setText(e.target.value)} />
        )}
      </Field>
      <div className="row">
        <button type="button" className="btn" onClick={run} disabled={busy || length < DRAFT_MIN}>
          {busy ? <Loader2 size={18} aria-hidden="true" className="spin" /> : <Sparkles size={18} aria-hidden="true" />}
          {busy ? 'Drafting…' : 'Draft the form'}
        </button>
        <span className="faint">Uses the AI assistant ({ai.provider}). Device passwords are never sent.</span>
      </div>
      <div aria-live="polite" className="stack">
        {result && (
          <Alert tone="info" title="AI draft loaded.">
            {result.used.length ? `It filled: ${result.used.map(name).join(', ')}. ` : 'It found nothing to fill. '}
            Check every value: the draft is validated and previewed like a plan you type yourself.
          </Alert>
        )}
        {result?.removed.length > 0 && (
          <Alert tone="warning">Left out because this device does not support it: {result.removed.map(name).join(', ')}.</Alert>
        )}
        {result?.dropped.length > 0 && (
          <Alert tone="warning">
            The assistant also suggested {result.dropped.map(name).join(' and ')}; that was removed. SSH users and custom
            commands are always entered by you.
          </Alert>
        )}
        <ErrorNote error={error} />
      </div>
    </section>
  )
}
