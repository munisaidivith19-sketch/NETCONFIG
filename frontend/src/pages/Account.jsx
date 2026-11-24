import { useEffect, useState } from 'react'
import { KeyRound } from 'lucide-react'
import { get, patch, post } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { Alert, Field, PageHeader, Panel } from '../components/ui.jsx'

/**
 * Settings → Security.
 * - Everyone can change their own password (needs the current one; POST /auth/password).
 * - Admins can also reset another user's password (PATCH /users/{id}). The server signs that user out
 *   everywhere and writes it to the audit log. Your own password is changed above, never "reset", so the
 *   current-password check cannot be skipped.
 */
export default function Account() {
  const { user, can } = useAuth()
  return (
    <>
      <PageHeader title="Security" subtitle={`${user.username} · ${user.role}`} />
      <ChangePassword />
      {can('admin') && <ResetPassword me={user} />}
    </>
  )
}

function ChangePassword() {
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
  )
}

function ResetPassword({ me }) {
  const [users, setUsers] = useState([])
  const [form, setForm] = useState({ id: '', new_password: '', repeat: '' })
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  useEffect(() => {
    get('/users')
      .then((list) => setUsers(list.filter((u) => u.id !== me.id)))
      .catch((err) => setMessage({ tone: 'danger', text: err.message }))
  }, [me.id])

  async function submit(e) {
    e.preventDefault()
    setMessage(null)
    if (form.new_password !== form.repeat) {
      setErrors({ repeat: 'The passwords do not match.' })
      return
    }
    const target = users.find((u) => u.id === form.id)
    setBusy(true)
    try {
      // unlock as well, so a locked-out user can sign in with the new password straight away
      await patch(`/users/${form.id}`, { new_password: form.new_password, unlock: true })
      setErrors({})
      setForm({ id: '', new_password: '', repeat: '' })
      setMessage({ tone: 'success', text: `Password reset for ${target.username}. They were signed out everywhere – share the new password privately.` })
    } catch (err) {
      setErrors(err.fields || {})
      setMessage({ tone: 'danger', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Reset a user's password" subtitle="Admins only. Use this when someone has forgotten their password.">
      <form onSubmit={submit} className="stack" style={{ maxWidth: 420 }}>
        {message && <Alert tone={message.tone}>{message.text}</Alert>}
        <Field label="User">
          {(p) => (
            <select {...p} className="select" value={form.id} onChange={set('id')} required>
              <option value="" disabled>Choose a user…</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.username} ({u.role})</option>)}
            </select>
          )}
        </Field>
        <Field label="New password" error={errors.new_password} hint="At least 12 characters. Must not contain their username.">
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
          <button className="btn primary" type="submit" disabled={busy || users.length === 0}>
            <KeyRound size={18} aria-hidden="true" /> {busy ? 'Resetting…' : 'Reset password'}
          </button>
        </div>
      </form>
    </Panel>
  )
}
