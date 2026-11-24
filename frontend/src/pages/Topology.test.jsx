import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Topology from './Topology.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const SW1 = 'a'.repeat(24)
const SW2 = 'b'.repeat(24)
const AP1 = 'c'.repeat(24)
const OVERVIEW = {
  kpis: {}, jobs_by_day: [], status_history: [], devices_by_category: {}, recent_jobs: [],
  last_poll: '2026-11-22T09:01:00Z',
  topology: {
    nodes: [
      { id: SW1, name: 'core-sw1', category: 'switch', model_name: 'IOSvL2', reachable: true, external: false },
      { id: SW2, name: 'access-sw2', category: 'switch', model_name: 'IOSvL2', reachable: false, external: false },
      { id: AP1, name: 'ap-lobby', category: 'ap', model_name: 'AP-515', reachable: null, external: false },
      { id: 'ext:isp-rtr', name: 'isp-rtr', category: 'router', external: true },
    ],
    links: [
      { a: SW1, b: SW2, a_port: 'Gi0/1', b_port: 'Gi0/24', source: 'cdp' },
      { a: SW2, b: AP1, a_port: 'Gi0/5', b_port: null, source: 'uplink' },
      { a: 'ext:isp-rtr', b: SW1, a_port: 'ge-0/0/0', b_port: 'Gi0/48', source: 'lldp' },
    ],
  },
}
const DEVICE = {
  id: SW1, name: 'core-sw1', model_name: 'IOSvL2', category: 'switch', support: 'experimental', mgmt_ip: '10.0.0.2',
  production: false, connection: { method: 'ssh', port: 22 }, status: { reachable: true }, facts: null, neighbors: [], vlans: [],
}

function mockApi(calls, overview = OVERVIEW) {
  globalThis.fetch = vi.fn((url) => {
    calls.push(url)
    let body = overview
    if (url.startsWith('/api/auth/me')) body = { id: 'u1', username: 'eng', role: 'engineer' }
    else if (url.startsWith('/api/devices/')) body = DEVICE
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

const renderPage = () => render(<MemoryRouter><AuthProvider><Topology /></AuthProvider></MemoryRouter>)
const map = () => screen.getByRole('group', { name: /Network map:/ })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Topology', () => {
  it('draws the map, counts devices by status and lists which port connects to which', async () => {
    mockApi([])
    renderPage()
    expect(await screen.findByRole('group', { name: /Network map: 4 devices and 3 links/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'All (3)' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Down (1)' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Not checked (1)' })).toBeTruthy()
    expect(screen.getByLabelText('Legend')).toBeTruthy()

    const table = screen.getByRole('table', { name: 'Connections between devices' })
    const rows = within(table).getAllByRole('row').slice(1).map((r) => r.textContent)
    expect(rows).toEqual([
      'core-sw1Gi0/1access-sw2Gi0/24CDP',
      'access-sw2Gi0/5ap-lobby—Uplink (set in Devices)',
      'isp-rtrge-0/0/0core-sw1Gi0/48LLDP',
    ])
  })

  it('filters by status and search; links to hidden devices disappear', async () => {
    mockApi([])
    renderPage()
    await screen.findByRole('group', { name: /Network map: 4 devices/ })

    fireEvent.click(screen.getByRole('button', { name: 'Down (1)' }))
    expect(within(map()).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
      expect.stringMatching(/^access-sw2, Switch, down/),
    ])
    expect(screen.getByText('No connections found yet')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'All (3)' }))
    fireEvent.change(screen.getByLabelText('Search devices by name or model'), { target: { value: 'sw' } })
    expect(map().getAttribute('aria-label')).toMatch(/2 devices and 1 links/)

    fireEvent.change(screen.getByLabelText('Search devices by name or model'), { target: { value: 'nothing-like-this' } })
    expect(screen.getByText('No device matches')).toBeTruthy()
  })

  it('opens a device from the connections table', async () => {
    const calls = []
    mockApi(calls)
    renderPage()
    const table = await screen.findByRole('table', { name: 'Connections between devices' })
    // Devices outside the inventory are plain text, not buttons.
    expect(within(table).queryByRole('button', { name: 'isp-rtr' })).toBeNull()
    fireEvent.click(within(table).getAllByRole('button', { name: 'core-sw1' })[0])
    expect(await screen.findByText('10.0.0.2')).toBeTruthy()
    expect(calls).toContain(`/api/devices/${SW1}`)
  })

  it('explains what to do when there are no devices', async () => {
    mockApi([], { ...OVERVIEW, topology: { nodes: [], links: [] } })
    renderPage()
    expect(await screen.findByText('No devices yet')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Add a device' }).getAttribute('href')).toBe('/devices')
  })
})
