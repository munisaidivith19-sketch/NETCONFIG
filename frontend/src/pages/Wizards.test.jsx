import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const ME = { id: 'u1', username: 'eng', role: 'engineer' }
const JOB_ID = 'f'.repeat(24)
const R1 = { id: '1'.repeat(24), name: 'r1', model_id: 'cisco-iosv', model_name: 'IOSv', category: 'router', capabilities: ['routed_if', 'ospf'], mgmt_ip: '10.0.0.11', production: false, connection: { method: 'ssh', port: 22 } }
const R2 = { ...R1, id: '2'.repeat(24), name: 'r2', mgmt_ip: '10.0.0.12' }
const SW1 = { id: '3'.repeat(24), name: 'sw1', model_id: 'cisco-iosvl2', model_name: 'IOSvL2', category: 'switch', capabilities: ['vlans', 'access', 'ssh'], mgmt_ip: '10.0.0.2', production: false, connection: { method: 'ssh', port: 22 } }
const SW2 = { ...SW1, id: '4'.repeat(24), name: 'sw2', mgmt_ip: '10.0.0.3' }
const NEW = { ...SW1, id: '5'.repeat(24), name: 'new-sw', mgmt_ip: '127.0.0.1', connection: { method: 'telnet_lab', port: 5000 } }
const MODEL = { id: 'cisco-iosvl2', name: 'IOSvL2', category: 'switch', port_examples: ['GigabitEthernet0/1'], capabilities: SW1.capabilities, os_driver: { id: 'cisco_ios', name: 'Cisco IOS / IOS-XE', support: 'experimental' } }

const step = (dev, extra = {}) => ({
  device_id: dev.id, device_name: dev.name, connection: dev.connection.method, mgmt_ip: dev.mgmt_ip, status: 'ready',
  commands: ['vlan 10'], warnings: [], timeline: [{ state: 'ready' }], output: '', backup: '', checks: [], notes: [], error: null, ...extra,
})
const job = (kind, steps, extra = {}) => ({
  id: JOB_ID, kind, status: 'ready', requested_by: { id: ME.id, username: 'eng' }, created_at: '2026-11-09T10:00:00Z',
  approval: { required: false }, plan: {}, steps, link_checks: [], ...extra,
})

function respond(routes, calls) {
  globalThis.fetch = vi.fn((url, init) => {
    const key = `${init?.method || 'GET'} ${url.split('?')[0]}`
    calls?.push({ key, body: init?.body ? JSON.parse(init.body) : undefined })
    const route = routes[key]
    const [status, body] = typeof route === 'function' ? route(init) : route || [404, { error: { message: 'not found' } }]
    return Promise.resolve({ ok: status < 300, status, text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)) })
  })
}

const renderAt = (path) => render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Router link wizard', () => {
  it('previews both sides with the match checks, then creates one job', async () => {
    const calls = []
    const preview = {
      ok: true, kind: 'link', errors: {}, warnings: ['Both sides are applied and verified first.'], production: false,
      checks: [{ name: 'Same subnet 10.255.0.0/30', ok: true, detail: '' }, { name: 'Same OSPF area (0)', ok: true, detail: '' }],
      steps: [
        { device_id: R1.id, device_name: 'r1', role: 'A', ok: true, commands: ['interface GigabitEthernet0/1', ' ip address 10.255.0.1 255.255.255.252'], verify_commands: [], revert_minutes: 10 },
        { device_id: R2.id, device_name: 'r2', role: 'B', ok: true, commands: ['interface GigabitEthernet0/1', ' ip address 10.255.0.2 255.255.255.252'], verify_commands: [], revert_minutes: 10 },
      ],
    }
    respond({
      'GET /api/auth/me': [200, ME],
      'GET /api/devices': [200, { items: [R1, R2, SW1], total: 3 }],
      'POST /api/jobs/preview': [200, preview],
      'POST /api/jobs': [201, job('link', [step(R1, { role: 'A' }), step(R2, { role: 'B' })])],
      [`GET /api/jobs/${JOB_ID}`]: [200, job('link', [step(R1, { role: 'A' }), step(R2, { role: 'B' })])],
    }, calls)
    renderAt('/configure/link')
    const [sideA, sideB] = await screen.findAllByLabelText('Device')
    expect(within(sideA).queryByText(/sw1/)).toBeNull() // only routers and Layer 3 switches
    fireEvent.change(sideA, { target: { value: R1.id } })
    fireEvent.change(sideB, { target: { value: R2.id } })
    const [ifA, ifB] = screen.getAllByLabelText('Interface')
    fireEvent.change(ifA, { target: { value: 'Gi0/1' } })
    fireEvent.change(ifB, { target: { value: 'Gi0/1' } })
    const [ridA, ridB] = screen.getAllByLabelText('Router ID')
    fireEvent.change(ridA, { target: { value: '1.1.1.1' } })
    fireEvent.change(ridB, { target: { value: '2.2.2.2' } })
    expect(screen.getByText('A gets 10.255.0.1, B gets 10.255.0.2')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Preview both sides/ }))
    expect(await screen.findByText('Same OSPF area (0)')).toBeTruthy()
    expect(screen.getAllByText(/ip address 10.255.0.2 255.255.255.252/).length).toBeGreaterThan(0)
    const body = calls.find((c) => c.key === 'POST /api/jobs/preview').body
    expect(body.link.a).toEqual({ device_id: R1.id, interface: 'Gi0/1', router_id: '1.1.1.1' })
    fireEvent.click(screen.getByRole('button', { name: 'Create job' }))
    expect(await screen.findByRole('form', { name: /Device credentials/ })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Devices in this job' })).toBeTruthy()
    expect(calls.find((c) => c.key === 'POST /api/jobs').body.link.b.device_id).toBe(R2.id)
  })
})

describe('First-time setup', () => {
  it('runs over a lab console without a device login', async () => {
    const calls = []
    const boot = job('bootstrap', [step(NEW)], { plan: { ssh: { username: 'netadmin', set_enable_secret: true } } })
    respond({
      'GET /api/auth/me': [200, ME],
      'GET /api/devices': [200, { items: [SW1, NEW], total: 2 }],
      'POST /api/jobs/preview': [200, { ok: true, kind: 'bootstrap', errors: {}, warnings: [], checks: [], production: false, steps: [{ device_id: NEW.id, device_name: 'new-sw', ok: true, commands: ['hostname sw9'], verify_commands: [], revert_minutes: 10 }] }],
      'POST /api/jobs': [201, boot],
      [`GET /api/jobs/${JOB_ID}`]: [200, boot],
      [`POST /api/jobs/${JOB_ID}/run`]: [202, { ...boot, status: 'queued' }],
    }, calls)
    renderAt('/configure/bootstrap')
    const select = await screen.findByLabelText('Device')
    expect(within(select).queryByText(/sw1/)).toBeNull() // SSH devices are not offered
    fireEvent.change(select, { target: { value: NEW.id } })
    expect(screen.getByText(/Insecure lab console/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Hostname'), { target: { value: 'sw9' } })
    fireEvent.change(screen.getByLabelText('Management address/prefix'), { target: { value: '10.10.10.2/24' } })
    fireEvent.click(screen.getByRole('button', { name: /Preview commands/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create job' }))
    const form = await screen.findByRole('form', { name: /Device credentials/ })
    fireEvent.change(within(form).getByLabelText(/Password for new local user "netadmin"/), { target: { value: 'Admin-User-Pw-5' } })
    fireEvent.change(within(form).getByLabelText('Repeat that password'), { target: { value: 'Admin-User-Pw-5' } })
    fireEvent.change(within(form).getByLabelText('New enable secret'), { target: { value: 'New-Enable-Pw-6' } })
    fireEvent.change(within(form).getByLabelText('Repeat the new enable secret'), { target: { value: 'New-Enable-Pw-6' } })
    fireEvent.click(within(form).getByRole('button', { name: /Run the first-time setup/ }))
    await vi.waitFor(() => expect(calls.some((c) => c.key === `POST /api/jobs/${JOB_ID}/run`)).toBe(true))
    const run = calls.find((c) => c.key === `POST /api/jobs/${JOB_ID}/run`).body
    expect(run).toEqual({ ssh_user_password: 'Admin-User-Pw-5', new_enable_secret: 'New-Enable-Pw-6' }) // no device login
    const preview = calls.find((c) => c.key === 'POST /api/jobs/preview').body
    expect(preview.bootstrap.mgmt).toEqual({ ip: '10.10.10.2/24', vlan: 1 })
  })
})

describe('Several switches', () => {
  it('previews the same plan for every chosen switch', async () => {
    const calls = []
    respond({
      'GET /api/auth/me': [200, ME],
      'GET /api/devices': [200, { items: [SW1, SW2, R1], total: 3 }],
      'GET /api/catalog/models/cisco-iosvl2': [200, MODEL],
      'GET /api/templates': [200, { items: [], total: 0 }],
      'POST /api/jobs/preview': [200, {
        ok: true, kind: 'multi', errors: {}, warnings: ['Switches are changed one after another.'], checks: [], production: false,
        steps: [SW1, SW2].map((d) => ({ device_id: d.id, device_name: d.name, ok: true, commands: ['vlan 10', ' name Sales'], verify_commands: ['show vlan brief'], revert_minutes: 10 })),
      }],
    }, calls)
    renderAt('/configure')
    fireEvent.click(await screen.findByRole('button', { name: /Several switches/ }))
    const group = await screen.findByRole('group', { name: 'Switches' })
    expect(within(group).queryByText('r1')).toBeNull()
    fireEvent.click(within(group).getByRole('button', { name: /sw1/ }))
    fireEvent.click(within(group).getByRole('button', { name: /sw2/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue with 2 switches' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add VLAN' }))
    fireEvent.change(screen.getByLabelText('VLAN ID'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Sales' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview commands' })[0])
    expect(await screen.findByText('Every switch (2)')).toBeTruthy()
    const body = calls.find((c) => c.key === 'POST /api/jobs/preview').body
    expect(body.device_ids).toEqual([SW1.id, SW2.id])
    expect(body.plan.vlans).toEqual([{ id: 10, name: 'Sales' }])
  })
})
