import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const ENGINEER = { id: 'u1', username: 'eng', role: 'engineer' }
const ADMIN = { id: 'u2', username: 'boss', role: 'admin' }
const ID = 'f'.repeat(24)
const DEVICE = {
  id: 'd'.repeat(24), name: 'lab-sw1', model_id: 'cisco-iosvl2', model_name: 'IOSvL2', category: 'switch',
  support: 'experimental', capabilities: ['vlans', 'access', 'ssh'], mgmt_ip: '10.0.0.2', production: false,
}
const MODEL = {
  id: 'cisco-iosvl2', name: 'IOSvL2', category: 'switch', port_examples: ['GigabitEthernet0/1'],
  capabilities: DEVICE.capabilities, os_driver: { id: 'cisco_ios', name: 'Cisco IOS / IOS-XE', support: 'experimental' },
}
const PREVIEW = {
  ok: true, errors: {}, warnings: [], unsupported: [], commands: ['vlan 10', ' name Sales'],
  verify_commands: ['show vlan brief'], commands_hash: 'a'.repeat(64), driver: { name: 'Cisco IOS / IOS-XE' },
  rollback: 'revert_timer', revert_minutes: 10, save_command: 'write memory', production: false,
}
const T = ['ready', 'queued', 'connecting', 'backing_up', 'checking', 'applying', 'verifying', 'saving', 'success']

function makeJob(status, extra = {}) {
  const upTo = T.indexOf(status) >= 0 ? T.slice(0, T.indexOf(status) + 1) : ['awaiting_approval']
  return {
    id: ID, status, requested_by: { id: ENGINEER.id, username: 'eng' }, created_at: '2026-11-08T10:00:00Z',
    approval: { required: false, expires_at: null, approved_by: null }, note: '', cancel_reason: null,
    plan: { vlans: [{ id: 10, name: 'Sales' }], ssh: { username: 'netadmin', set_enable_secret: false } },
    steps: [{
      device_name: 'lab-sw1', connection: 'ssh', commands: ['vlan 10', ' name Sales'], warnings: [],
      timeline: upTo.map((state) => ({ state, at: '2026-11-08T10:00:00Z' })), output: '', backup: '',
      checks: [], notes: [], error: null,
    }],
    ...extra,
  }
}

function respond(routes, calls) {
  globalThis.fetch = vi.fn((url, init) => {
    const key = `${init?.method || 'GET'} ${url.split('?')[0]}`
    calls?.push({ key, body: init?.body ? JSON.parse(init.body) : undefined })
    const route = routes[key]
    const [status, body] = typeof route === 'function' ? route(init) : route || [404, { error: { message: 'not found' } }]
    return Promise.resolve({ ok: status < 300, status, text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)) })
  })
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Push and verify', () => {
  it('creates a job, asks for credentials only at run time, and shows live progress', async () => {
    const calls = []
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const done = makeJob('success', {
      steps: [{
        ...makeJob('success').steps[0], output: '>>> configure terminal revert timer 10\n>>> configure confirm',
        checks: [{ name: 'VLAN 10 Sales exists', ok: true, detail: 'found in show vlan brief', required: true }],
        notes: ['Change confirmed; the rollback timer is cancelled.'],
      }],
    })
    respond({
      'GET /api/auth/me': [200, ENGINEER],
      'GET /api/health': [200, { status: 'ok', simulation: true }],
      'GET /api/devices': [200, { items: [DEVICE], total: 1 }],
      'GET /api/catalog/models/cisco-iosvl2': [200, MODEL],
      'POST /api/plans/preview': [200, PREVIEW],
      'POST /api/jobs': [201, makeJob('ready')],
      [`POST /api/jobs/${ID}/run`]: [202, makeJob('queued')],
      [`GET /api/jobs/${ID}`]: [200, done],
    }, calls)
    renderAt('/configure')
    expect(await screen.findByText(/Simulation mode/)).toBeTruthy()
    fireEvent.click(await screen.findByRole('button', { name: /lab-sw1/ }))
    fireEvent.click((await screen.findAllByRole('button', { name: 'Preview commands' }))[0])
    fireEvent.click(await screen.findByRole('button', { name: /Continue/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create job' }))

    // The job was created without any credential.
    const created = calls.find((c) => c.key === 'POST /api/jobs').body
    expect(created.device_id).toBe(DEVICE.id)
    expect(JSON.stringify(created)).not.toMatch(/password|Pw-/i)

    const form = await screen.findByRole('form', { name: /Device credentials/ })
    fireEvent.change(within(form).getByLabelText('Device username'), { target: { value: 'netops' } })
    fireEvent.change(within(form).getByLabelText('Device password'), { target: { value: 'Device-Login-Pw-1' } })
    // The plan creates a local user, so its password is asked for (twice) and checked like the backend does.
    fireEvent.change(within(form).getByLabelText(/Password for new local user "netadmin"/), { target: { value: 'Plan-User-Pw-3' } })
    fireEvent.change(within(form).getByLabelText('Repeat that password'), { target: { value: 'Plan-User-Pw-X' } })
    fireEvent.click(within(form).getByRole('button', { name: /Run the push/ }))
    expect(await within(form).findByText('The two entries do not match')).toBeTruthy()
    expect(calls.some((c) => c.key.endsWith('/run'))).toBe(false)
    fireEvent.change(within(form).getByLabelText('Repeat that password'), { target: { value: 'Plan-User-Pw-3' } })
    fireEvent.click(within(form).getByRole('button', { name: /Run the push/ }))

    expect(await screen.findByText(/Done\./, {}, { timeout: 4000 })).toBeTruthy()
    const run = calls.find((c) => c.key === `POST /api/jobs/${ID}/run`).body
    expect(run).toEqual({ username: 'netops', password: 'Device-Login-Pw-1', ssh_user_password: 'Plan-User-Pw-3' })
    expect(screen.getByRole('list', { name: 'Push progress' })).toBeTruthy()
    expect(screen.getByText('VLAN 10 Sales exists')).toBeTruthy()
    // Credentials never reach browser storage and are gone from the page.
    expect(setItem.mock.calls.flat().join(' ')).not.toMatch(/Pw-1|Pw-3/)
    expect(document.body.innerHTML).not.toMatch(/Device-Login-Pw-1|Plan-User-Pw-3/)
  })

  it('lets an admin approve a production request in History', async () => {
    const waiting = makeJob('awaiting_approval', {
      approval: { required: true, expires_at: '2026-11-09T10:00:00Z', approved_by: null },
    })
    const calls = []
    respond({
      'GET /api/auth/me': [200, ADMIN],
      'GET /api/health': [200, { status: 'ok', simulation: false }],
      'GET /api/jobs': [200, { items: [waiting], total: 1, page: 1, page_size: 25 }],
      [`GET /api/jobs/${ID}`]: [200, waiting],
      [`POST /api/jobs/${ID}/approve`]: [200, makeJob('ready', { approval: { required: true, approved_by: { username: 'boss' } } })],
    }, calls)
    renderAt('/history')
    fireEvent.click(await screen.findByRole('link', { name: 'lab-sw1' }))
    expect(await screen.findByText(/Waiting for a second person/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    // Admins may run approved jobs too (backend: requester or admin); the credentials form appears.
    expect(await screen.findByRole('form', { name: /Device credentials/ })).toBeTruthy()
    expect(calls.some((c) => c.key === `POST /api/jobs/${ID}/approve`)).toBe(true)
  })

  it('does not offer approval to the requester', async () => {
    const own = makeJob('awaiting_approval', {
      requested_by: { id: ADMIN.id, username: 'boss' },
      approval: { required: true, expires_at: '2026-11-09T10:00:00Z', approved_by: null },
    })
    respond({
      'GET /api/auth/me': [200, ADMIN],
      'GET /api/health': [200, { status: 'ok' }],
      [`GET /api/jobs/${ID}`]: [200, own],
    })
    renderAt(`/history/${ID}`)
    expect(await screen.findByText(/another admin has to approve it/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull()
  })
})

describe('SSH host keys', () => {
  it('shows a changed key and accepts it only after confirmation', async () => {
    const calls = []
    const key = {
      id: 'k'.repeat(24), host: '10.0.0.2', port: 22, key_type: 'ssh-ed25519', fingerprint: 'SHA256:old',
      first_seen: '2026-11-01T10:00:00Z', last_seen: '2026-11-07T10:00:00Z', accepted_by: null,
      pending: { key_type: 'ssh-ed25519', fingerprint: 'SHA256:new', seen_at: '2026-11-08T10:00:00Z' },
    }
    respond({
      'GET /api/auth/me': [200, ADMIN],
      'GET /api/health': [200, { status: 'ok' }],
      'GET /api/hostkeys': [200, [key]],
      [`POST /api/hostkeys/${key.id}/accept`]: [200, { ...key, fingerprint: 'SHA256:new', pending: null }],
    }, calls)
    renderAt('/admin/host-keys')
    expect(await screen.findByText(/1 device offered a different key/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Accept new key' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('SHA256:new')).toBeTruthy()
    expect(calls.some((c) => c.key.endsWith('/accept'))).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept new key' }))
    await vi.waitFor(() => expect(calls.some((c) => c.key.endsWith('/accept'))).toBe(true))
    expect(JSON.stringify(calls)).not.toMatch(/key_b64/)
  })
})
