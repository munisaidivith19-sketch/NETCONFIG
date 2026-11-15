import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Overview from './Overview.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const SW1 = 'a'.repeat(24)
const SW2 = 'b'.repeat(24)
const days = Array.from({ length: 14 }, (_, i) => ({ date: `2026-11-${String(i + 2).padStart(2, '0')}`, success: i % 3, failed: i === 13 ? 1 : 0, other: 0 }))
const OVERVIEW = {
  kpis: { devices: 2, up: 1, down: 1, unknown: 0, model_mismatches: 1, jobs_7d: 5, success_7d: 4, failed_7d: 1, success_rate_7d: 80, waiting: 1, running: 0 },
  jobs_by_day: days,
  status_history: [{ at: '2026-11-15T09:00:00Z', up: 1, down: 1, unknown: 0 }, { at: '2026-11-15T09:01:00Z', up: 2, down: 0, unknown: 0 }],
  devices_by_category: { switch: 2 },
  topology: {
    nodes: [
      { id: SW1, name: 'sw1', category: 'switch', model_name: 'IOSvL2', reachable: true, external: false },
      { id: SW2, name: 'sw2', category: 'switch', model_name: 'IOSvL2', reachable: false, external: false },
      { id: 'ext:core-rtr9', name: 'core-rtr9', category: 'router', external: true },
    ],
    links: [{ a: SW1, b: SW2, a_port: 'Gi0/1', b_port: 'Gi0/2', source: 'cdp' }],
  },
  recent_jobs: [{ id: 'j1', status: 'success', kind: 'single', created_at: '2026-11-15T09:00:00Z', devices: ['sw1'], requested_by: 'eng' }],
  last_poll: '2026-11-15T09:01:00Z',
}
const DEVICE = {
  id: SW1, name: 'sw1', model_name: 'IOSvL2', category: 'switch', support: 'experimental', mgmt_ip: '10.0.0.2', production: false,
  connection: { method: 'ssh', port: 22 }, status: { reachable: true, checked_at: '2026-11-15T09:01:00Z' }, facts: null, neighbors: [], vlans: [],
}
const FOUND = {
  ...DEVICE, vlans: [{ id: 10, name: 'Staff' }],
  facts: { source: 'cli', model: 'WS-C2960X', version: '15.2', serial: 'X1', read_at: '2026-11-15T09:02:00Z',
    match: { status: 'mismatch', message: 'The device reports model WS-C2960X, but the inventory says IOSvL2.' } },
}

function mockApi(calls, overview = OVERVIEW) {
  globalThis.fetch = vi.fn((url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', body: opts.body })
    let body = overview
    if (url.startsWith('/api/auth/me')) body = { id: 'u1', username: 'eng', role: 'engineer' }
    else if (url.endsWith('/discover')) body = FOUND
    else if (url.startsWith(`/api/devices/${SW1}`)) body = DEVICE
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

function renderPage() {
  return render(<MemoryRouter><AuthProvider><Overview /></AuthProvider></MemoryRouter>)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Overview', () => {
  it('shows KPIs, the map and the charts from the API', async () => {
    mockApi([])
    renderPage()
    expect(await screen.findByText('1 / 2')).toBeTruthy()
    expect(screen.getByText(/80% succeeded/)).toBeTruthy()
    const map = screen.getByRole('group', { name: /Network map: 3 devices and 1 links/ })
    expect(within(map).getByRole('button', { name: /sw2, Switch, down/ })).toBeTruthy()
    expect(within(map).getByRole('button', { name: /core-rtr9, neighbour outside the inventory/ })).toBeTruthy()
    expect(screen.getByRole('img', { name: /Changes per day/ })).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: /Show as table/ })[0])
    expect(screen.getAllByRole('row')).toHaveLength(15) // header + 14 days
  })

  it('selects a device with the keyboard and reads its facts without keeping the password', async () => {
    const calls = []
    mockApi(calls)
    renderPage()
    const sw1 = await screen.findByRole('button', { name: /^sw1,/ })
    sw1.focus()
    fireEvent.keyDown(sw1, { key: 'ArrowRight' })
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /^sw2,/ }))
    fireEvent.keyDown(sw1, { key: 'Enter' })
    fireEvent.change(await screen.findByLabelText('Device username'), { target: { value: 'netadmin' } })
    const password = screen.getByLabelText('Device password')
    fireEvent.change(password, { target: { value: 'Dev1ce-Login-Secret' } })
    fireEvent.click(screen.getByRole('button', { name: /Read device facts/ }))
    expect(await screen.findByText(/inventory says IOSvL2/)).toBeTruthy()
    const sent = calls.find((c) => c.url.endsWith('/discover'))
    expect(sent.method).toBe('POST')
    expect(JSON.parse(sent.body)).toEqual({ username: 'netadmin', password: 'Dev1ce-Login-Secret' })
    await waitFor(() => expect(screen.getByLabelText('Device password').value).toBe(''))
    expect(JSON.stringify(window.localStorage)).not.toContain('Dev1ce')
    expect(JSON.stringify(window.sessionStorage)).not.toContain('Dev1ce')
  })

  it('shows empty states when there is nothing yet', async () => {
    const none = { ...OVERVIEW, kpis: { ...OVERVIEW.kpis, devices: 0, up: 0, down: 0, success_rate_7d: null, jobs_7d: 0 },
      topology: { nodes: [], links: [] }, status_history: [], devices_by_category: {}, recent_jobs: [] }
    mockApi([], none)
    renderPage()
    expect(await screen.findByText('No devices yet', { selector: 'strong' })).toBeTruthy()
    expect(screen.getByText('No status checks yet')).toBeTruthy()
    expect(screen.getByText('No changes yet')).toBeTruthy()
  })
})
