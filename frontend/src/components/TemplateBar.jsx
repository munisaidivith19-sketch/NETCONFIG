import { useCallback, useEffect, useState } from 'react'
import { BookmarkPlus, FileInput, Trash2 } from 'lucide-react'
import { del, get, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { NOTE_HINT, NOTE_PATTERN } from '../lib/jobs.js'
import { fromPlan, toPlan } from '../lib/plan.js'
import { Alert, ErrorNote, Field } from './ui.jsx'

const NAME = /^[A-Za-z0-9 _.()-]{1,60}$/

/**
 * Saved templates: load one into the requirements form, or save the current form as one. A template only
 * pre-fills the form; the plan is validated again for the chosen device. Secrets are never part of it.
 */
export default function TemplateBar({ form, setForm, osId }) {
  const { user, can } = useAuth()
  const [items, setItems] = useState([])
  const [chosen, setChosen] = useState('')
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  const load = useCallback(async () => {
    try {
      setItems((await get('/templates')).items || [])
    } catch {
      setItems([]) // templates are optional: the wizard works without them
    }
  }, [])
  useEffect(() => { load() }, [load])

  const usable = items.filter((t) => !t.os_id || t.os_id === osId)
  const current = usable.find((t) => t.id === chosen)
  const canDelete = current && (current.created_by?.id === user?.id || can('admin'))

  function apply() {
    if (!current) return
    setForm(() => fromPlan(current.plan))
    setMessage(`Loaded "${current.name}". Check every section: it is validated again for this device.`)
  }

  async function save() {
    setError(null)
    try {
      const t = await post('/templates', { name: name.trim(), description: description.trim(), os_id: osId || null, plan: toPlan(form) })
      setMessage(`Saved as "${t.name}".`)
      setSaving(false)
      setName('')
      setDescription('')
      await load()
      setChosen(t.id)
    } catch (err) {
      setError(err)
    }
  }

  async function remove() {
    setError(null)
    try {
      await del(`/templates/${current.id}`)
      setMessage(`Deleted "${current.name}".`)
      setChosen('')
      await load()
    } catch (err) {
      setError(err)
    }
  }

  const badName = name && !NAME.test(name.trim())
  const badDescription = !NOTE_PATTERN.test(description)

  return (
    <section className="section-card stack" aria-label="Templates">
      <div className="row between">
        <h3 style={{ margin: 0 }}>Templates</h3>
        <button type="button" className="btn small ghost" aria-expanded={saving} onClick={() => setSaving((v) => !v)}>
          <BookmarkPlus size={16} aria-hidden="true" /> Save as template
        </button>
      </div>
      {usable.length > 0 ? (
        <div className="row">
          <Field label="Start from a template">
            {(props) => (
              <select {...props} className="select" value={chosen} onChange={(e) => setChosen(e.target.value)}>
                <option value="">Choose…</option>
                {usable.map((t) => <option key={t.id} value={t.id}>{t.name}{t.description ? ` – ${t.description}` : ''}</option>)}
              </select>
            )}
          </Field>
          <button type="button" className="btn" disabled={!current} onClick={apply}>
            <FileInput size={18} aria-hidden="true" /> Load
          </button>
          {canDelete && (
            <button type="button" className="btn ghost" onClick={remove} aria-label={`Delete template ${current.name}`}>
              <Trash2 size={18} aria-hidden="true" />
            </button>
          )}
        </div>
      ) : (
        <p className="faint" style={{ margin: 0 }}>No templates for this OS yet. Fill in the form and save it to reuse it.</p>
      )}
      {saving && (
        <div className="form-grid">
          <Field label="Template name" error={badName ? 'Letters, digits, spaces and _ . ( ) - only (max 60)' : null}>
            {(props) => <input {...props} className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Description (optional)" error={badDescription ? NOTE_HINT : null}>
            {(props) => <input {...props} className="input" value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} />}
          </Field>
          <div className="form-actions">
            <button type="button" className="btn primary" disabled={!name.trim() || badName || badDescription} onClick={save}>Save template</button>
          </div>
        </div>
      )}
      {message && <Alert tone="info">{message}</Alert>}
      <ErrorNote error={error} />
    </section>
  )
}
