import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { LogIn, Network } from 'lucide-react'
import { useAuth } from '../lib/auth.jsx'
import { Alert, Field } from '../components/ui.jsx'

export default function Login() {
  const { user, login, expired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={location.state?.from || '/'} replace />

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(username.trim(), password)
      setPassword('')
      navigate(location.state?.from || '/', { replace: true })
    } catch (err) {
      setPassword('')
      setError(err.status === 422 ? 'Enter your username and password.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <main className="glass strong login-card">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Network size={22} />
          </span>
          <span>
            <strong>NetConfig Studio</strong>
            <span>Sign in to configure your network</span>
          </span>
        </div>
        <form onSubmit={submit} noValidate>
          {expired && !error && <Alert tone="warning">Your session ended. Please sign in again.</Alert>}
          {error && <Alert tone="danger">{error}</Alert>}
          <Field label="Username">
            {(props) => (
              <input
                {...props}
                className="input"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                maxLength={32}
                required
                autoFocus
              />
            )}
          </Field>
          <Field label="Password">
            {(props) => (
              <input
                {...props}
                className="input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={128}
                required
              />
            )}
          </Field>
          <button className="btn primary" type="submit" disabled={busy || !username || !password}>
            <LogIn size={18} aria-hidden="true" /> {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="login-foot">
          Runs only on this computer (127.0.0.1). After 5 wrong passwords the account locks for 15 minutes.
        </p>
      </main>
    </div>
  )
}
