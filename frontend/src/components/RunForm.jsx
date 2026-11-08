import { useState } from 'react'
import { Play, ShieldAlert } from 'lucide-react'
import { post } from '../lib/api.js'
import { checkNewSecret, secretsNeeded } from '../lib/jobs.js'
import { Alert, ErrorNote, Field } from './ui.jsx'

const EMPTY = {
  username: '', password: '', enable_secret: '',
  ssh_user_password: '', ssh_user_password2: '', new_enable_secret: '', new_enable_secret2: '',
}

/**
 * Device credentials for ONE run. They live only in this component's state, go to POST /jobs/{id}/run once,
 * and are cleared from it straight after. Nothing is put in localStorage or the URL.
 */
export default function RunForm({ job, onStarted }) {
  const [v, setV] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const need = secretsNeeded(job.plan)
  const method = job.steps?.[0]?.connection

  const set = (k) => (e) => setV((old) => ({ ...old, [k]: e.target.value }))

  function check() {
    const errs = {}
    if (!v.username.trim()) errs.username = 'Required'
    if (!v.password) errs.password = 'Required'
    if (need.sshUser) {
      const e = checkNewSecret(v.ssh_user_password, v.ssh_user_password2)
      if (e) errs.ssh_user_password = e
    }
    if (need.enableSecret) {
      const e = checkNewSecret(v.new_enable_secret, v.new_enable_secret2)
      if (e) errs.new_enable_secret = e
    }
    return errs
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    const errs = check()
    setErrors(errs)
    if (Object.keys(errs).length) return
    const body = { username: v.username.trim(), password: v.password }
    if (v.enable_secret) body.enable_secret = v.enable_secret
    if (need.sshUser) body.ssh_user_password = v.ssh_user_password
    if (need.enableSecret) body.new_enable_secret = v.new_enable_secret
    setBusy(true)
    try {
      const started = await post(`/jobs/${job.id}/run`, body)
      setV(EMPTY)
      onStarted(started)
    } catch (err) {
      setV((old) => ({ ...old, password: '', enable_secret: '' })) // never keep a rejected login around
      setErrors(err.fields || {})
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const input = (name, label, { hint, auto = 'off', type = 'password' } = {}) => (
    <Field label={label} hint={hint} error={errors[name]}>
      {(props) => (
        <input {...props} className="input" type={type} name={name} value={v[name]} onChange={set(name)}
          autoComplete={auto} spellCheck={false} maxLength={128} />
      )}
    </Field>
  )

  return (
    <form className="stack" onSubmit={submit} noValidate aria-label="Device credentials for this run">
      <Alert tone="info" title="Used once, never stored.">
        These are sent to the local backend for this push only, kept in memory while it runs, and wiped when it
        ends. They are not saved in the database, the logs or this browser.
      </Alert>
      {method === 'telnet_lab' && (
        <Alert tone="warning" title="Insecure lab console.">Telnet sends the password in clear text. Use it only on an emulator or isolated lab.</Alert>
      )}
      <div className="form-grid">
        {input('username', 'Device username', { type: 'text', auto: 'off' })}
        {input('password', 'Device password')}
        {input('enable_secret', 'Enable secret (if the device asks)', { hint: 'Leave empty if the user lands in privileged mode.' })}
      </div>
      {(need.sshUser || need.enableSecret) && (
        <fieldset className="section-card stack">
          <legend><ShieldAlert size={16} aria-hidden="true" /> Secrets this plan sets on the device</legend>
          <div className="form-grid">
            {need.sshUser && input('ssh_user_password', `Password for new local user "${need.sshUser}"`, { auto: 'new-password', hint: '8–64 characters, no spaces or # ? ; | " \' ^' })}
            {need.sshUser && input('ssh_user_password2', 'Repeat that password', { auto: 'new-password' })}
            {need.enableSecret && input('new_enable_secret', 'New enable secret', { auto: 'new-password' })}
            {need.enableSecret && input('new_enable_secret2', 'Repeat the new enable secret', { auto: 'new-password' })}
          </div>
        </fieldset>
      )}
      <ErrorNote error={error} />
      <div className="form-actions">
        <button type="submit" className="btn primary" disabled={busy}>
          <Play size={18} aria-hidden="true" /> {busy ? 'Starting…' : 'Run the push'}
        </button>
      </div>
    </form>
  )
}
