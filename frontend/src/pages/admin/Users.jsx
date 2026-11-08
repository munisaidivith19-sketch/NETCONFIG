import { useCallback, useEffect, useState } from 'react'
import { Lock, Plus, UserCog, Users as UsersIcon } from 'lucide-react'
import { del, get, patch, post } from '../../lib/api.js'
import { useAuth } from '../../lib/auth.jsx'
import { Alert, Badge, Dialog, Empty, ErrorNote, Field, PageHeader, Panel, SkeletonRows, formatDate } from '../../components/ui.jsx'

const ROLES = ['viewer', 'engineer', 'admin']
const ROLE_HELP = {
  viewer: 'Read only.',
  engineer: 'Create plans, push to lab devices, request production pushes.',
  admin: 'Everything, plus users, settings and production approvals.',
}

export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState(null)

  const load = useCallback(() => {
    get('/users').then(setUsers).catch(setError)
  }, [])
  useEffect(load, [load])

  async function update(u, changes, text) {
    setError(null)
    try {
      await patch(`/users/${u.id}`, changes)
      setNotice(text)
      load()
    } catch (err) {
      setError(err)
    }
  }

  async function remove(u) {
    if (!window.confirm(`Delete the account “${u.username}”? This cannot be undone.`)) return
    try {
      await del(`/users/${u.id}`)
      setNotice(`Deleted ${u.username}.`)
      load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <>
      <PageHeader title="Users" subtitle="Who can sign in, and what each role may do.">
        <button className="btn primary" type="button" onClick={() => setAdding(true)}>
          <Plus size={18} aria-hidden="true" /> Add user
        </button>
      </PageHeader>
      {notice && <Alert tone="success">{notice}</Alert>}
      <ErrorNote error={error} />
      <Panel title="Accounts">
        {!users ? (
          <SkeletonRows />
        ) : users.length === 0 ? (
          <Empty icon={UsersIcon} title="No users yet" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="cell-title">{u.username}{u.id === me.id && <span className="faint"> (you)</span>}</td>
                    <td>
                      <label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.username}</label>
                      <select id={`role-${u.id}`} className="select" value={u.role}
                        onChange={(e) => update(u, { role: e.target.value }, `${u.username} is now ${e.target.value}.`)}>
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td>
                      {u.disabled ? <Badge tone="danger">Disabled</Badge>
                        : u.locked ? <Badge tone="warning"><Lock size={12} aria-hidden="true" /> Locked</Badge>
                          : <Badge tone="success" dot>Active</Badge>}
                    </td>
                    <td className="faint">{formatDate(u.created_at)}</td>
                    <td>
                      <div className="row" style={{ justifyContent: 'flex-end' }}>
                        {u.locked && (
                          <button className="btn small" type="button" onClick={() => update(u, { unlock: true }, `Unlocked ${u.username}.`)}>
                            Unlock
                          </button>
                        )}
                        {u.id !== me.id && (
                          <button className="btn small" type="button"
                            onClick={() => update(u, { disabled: !u.disabled }, `${u.username} ${u.disabled ? 'enabled' : 'disabled'}.`)}>
                            {u.disabled ? 'Enable' : 'Disable'}
                          </button>
                        )}
                        {u.id !== me.id && (
                          <button className="btn small danger" type="button" onClick={() => remove(u)}>Delete</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel title="Roles">
        <ul className="stack" style={{ margin: 0, paddingLeft: 18 }}>
          {ROLES.map((r) => <li key={r}><strong>{r}</strong> – {ROLE_HELP[r]}</li>)}
        </ul>
      </Panel>
      {adding && (
        <AddUser
          onClose={() => setAdding(false)}
          onDone={(name) => {
            setAdding(false)
            setNotice(`Created ${name}.`)
            load()
          }}
        />
      )}
    </>
  )
}

function AddUser({ onClose, onDone }) {
  const [form, setForm] = useState({ username: '', password: '', role: 'engineer' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await post('/users', form)
      onDone(form.username)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Add user" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        {error && !Object.keys(error.fields).length && <ErrorNote error={error} />}
        <Field label="Username" hint="3–32 characters: letters, digits, . _ -" error={error?.fields?.username}>
          {(p) => <input {...p} className="input" value={form.username} onChange={set('username')} maxLength={32} autoComplete="off" required />}
        </Field>
        <Field label="Temporary password" hint="At least 12 characters. Share it privately." error={error?.fields?.password}>
          {(p) => <input {...p} className="input" type="password" value={form.password} onChange={set('password')} autoComplete="new-password" maxLength={72} required />}
        </Field>
        <Field label="Role" hint={ROLE_HELP[form.role]}>
          {(p) => (
            <select {...p} className="select" value={form.role} onChange={set('role')}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
        </Field>
        <div className="form-actions">
          <button className="btn ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="btn primary" type="submit" disabled={busy}>
            <UserCog size={18} aria-hidden="true" /> {busy ? 'Creating…' : 'Create user'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
