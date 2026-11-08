import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const ME = { id: 'u1', username: 'eng', role: 'engineer' }
const DEVICE = {
  id: 'd'.repeat(24), name: 'lab-sw1', model_id: 'cisco-c9300-24t', model_name: 'C9300-24T', category: 'l3switch',
  support: 'experimental', capabilities: ['vlans', 'access', 'svi', 'ssh'], mgmt_ip: '10.0.0.2', production: false,
}
const MODEL = {
  id: 'cisco-c9300-24t', name: 'C9300-24T', category: 'l3switch', port_examples: ['GigabitEthernet1/0/1'],
  capabilities: DEVICE.capabilities, os_driver: { id: 'cisco_ios', name: 'Cisco IOS / IOS-XE', support: 'experimental' },
}

function respond(routes, calls) {
  globalThis.fetch = vi.fn((url, init) => {
    const key = `${init?.method || 'GET'} ${url.split('?')[0]}`
    calls?.push({ key, body: init?.body ? JSON.parse(init.body) : undefined })
    const route = routes[key]
    const [status, body] = typeof route === 'function' ? route(init) : route || [404, { error: { message: 'not found' } }]
    return Promise.resolve({ ok: status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) })
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

const BASE = {
  'GET /api/auth/me': [200, ME],
  'GET /api/devices': [200, { items: [DEVICE], total: 1 }],
  'GET /api/catalog/models/cisco-c9300-24t': [200, MODEL],
}

describe('Configure wizard', () => {
  it('previews commands from the API and shows them masked', async () => {
    const calls = []
    respond({
      ...BASE,
      'POST /api/plans/preview': [200, {
        ok: true, errors: {}, warnings: ['The Cisco IOS / IOS-XE driver is experimental.'], unsupported: [],
        commands: ['vlan 10', ' name Sales'], verify_commands: ['show vlan brief'], commands_hash: 'a'.repeat(64),
        driver: { name: 'Cisco IOS / IOS-XE', support: 'experimental' }, rollback: 'revert_timer', revert_minutes: 10,
        save_command: 'write memory', production: false,
      }],
    }, calls)
    renderAt('/configure')
    fireEvent.click(await screen.findByRole('button', { name: /lab-sw1/ }))
    expect(await screen.findByRole('heading', { name: 'Requirements' })).toBeTruthy()
    // Sections the model cannot do are not shown.
    expect(screen.queryByRole('heading', { name: /NAT overload/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Add VLAN' }))
    fireEvent.change(screen.getByLabelText('VLAN ID'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Sales' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview commands' })[0])
    const code = await screen.findByLabelText(/2 configuration commands/)
    expect(within(code).getByText('vlan 10')).toBeTruthy()
    const sent = calls.find((c) => c.key === 'POST /api/plans/preview').body
    expect(sent.device_id).toBe(DEVICE.id)
    expect(sent.plan.vlans).toEqual([{ id: 10, name: 'Sales' }])
    expect(JSON.stringify(sent)).not.toMatch(/password/i)
  })

  it('shows field errors from the backend next to the field', async () => {
    respond({
      ...BASE,
      'POST /api/plans/preview': [200, {
        ok: false, errors: { 'vlans.0.id': 'VLANs 1002–1005 are reserved' }, warnings: [], unsupported: [],
        commands: [], verify_commands: [], commands_hash: null, driver: { name: 'Cisco IOS / IOS-XE' },
      }],
    })
    renderAt('/configure')
    fireEvent.click(await screen.findByRole('button', { name: /lab-sw1/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add VLAN' }))
    fireEvent.change(screen.getByLabelText('VLAN ID'), { target: { value: '1002' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview commands' })[0])
    expect(await screen.findByText(/1 problem to fix/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Fix' }))
    const input = await screen.findByLabelText('VLAN ID')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    const message = document.getElementById(input.getAttribute('aria-describedby'))
    expect(message.textContent).toBe('VLANs 1002–1005 are reserved')
  })
})
