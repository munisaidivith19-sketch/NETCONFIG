import { useState } from 'react'
import { post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { Alert, Field, PageHeader, Panel } from '../components/ui.jsx'

export default function Account() {
  const { user } = useAuth()
  const [form, setForm] = useState({ current_password: '', new_password: '', repeat: '' })
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setMessage(null)
    if (form.new_password !== form.repeat) {
      setErrors({ repeat: 'The new passwords do not match.' })
      return
    }
    setBusy(true)
    try {
      await post('/auth/password', { current_password: form.current_password, new_password: form.new_password })
      setErrors({})
      setForm({ current_password: '', new_password: '', repeat: '' })
      setMessage({ tone: 'success', text: 'Password changed. Your other sessions were signed out.' })
    } catch (err) {
      setErrors(err.fields || {})
      setMessage({ tone: 'danger', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Your account" subtitle={`${user.username} · ${user.role}`} />
      <Panel title="Change password" subtitle="At least 12 characters. A passphrase of a few words works well.">
        <form onSubmit={submit} className="stack" style={{ maxWidth: 420 }}>
          {message && <Alert tone={message.tone}>{message.text}</Alert>}
          <Field label="Current password" error={errors.current_password}>
            {(p) => (
              <input {...p} className="input" type="password" autoComplete="current-password"
                value={form.current_password} onChange={set('current_password')} required />
            )}
          </Field>
          <Field label="New password" error={errors.new_password} hint="Must not contain your username.">
            {(p) => (
              <input {...p} className="input" type="password" autoComplete="new-password" minLength={12}
                maxLength={72} value={form.new_password} onChange={set('new_password')} required />
            )}
          </Field>
          <Field label="Repeat new password" error={errors.repeat}>
            {(p) => (
              <input {...p} className="input" type="password" autoComplete="new-password"
                value={form.repeat} onChange={set('repeat')} required />
            )}
          </Field>
          <div className="form-actions">
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Change password'}
            </button>
          </div>
        </form>
      </Panel>
    </>
  )
}
