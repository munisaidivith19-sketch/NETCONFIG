import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Devices from './Devices.jsx'
import { AuthProvider } from '../lib/auth.jsx'

const SW = {
  id: 'a'.repeat(24), name: 'sw1', model_id: 'cisco-iosvl2', model_name: 'IOSvL2', brand: 'Cisco', category: 'switch',
  support: 'experimental', os_name: 'Cisco IOS', capabilities: ['access'], mgmt_ip: '10.0.0.2', production: false,
  connection: { method: 'ssh', port: 22 }, tags: [], status: {}, location: '', uplink: null, facts: null,
}
const AP = {
  ...SW, id: 'b'.repeat(24), name: 'ap-lobby', model_name: 'C9120AXI', category: 'ap', support: 'inventory',
  os_name: 'Controller-managed access point', mgmt_ip: null, connection: { method: 'none' },
  uplink: { device_id: SW.id, interface: 'GigabitEthernet0/5' },
}
const CAM = {
  ...SW, id: 'c'.repeat(24), name: 'cam1', model_name: 'P3245-V', category: 'camera', support: 'inventory',
  os_name: 'IP camera (ONVIF, read only)', mgmt_ip: '10.0.5.20', connection: { method: 'none' },
}
const FACTS = { source: 'onvif', read_at: '2026-11-15T10:00:00Z', manufacturer: 'AXIS', model: 'P3245-V', serialnumber: 'ACCC8E000001' }

function mockApi(calls) {
  let cam = CAM
  globalThis.fetch = vi.fn((url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', body: opts.body })
    let body = { items: [SW, AP, cam], total: 3 }
    if (url.startsWith('/api/auth/me')) body = { id: 'u1', username: 'eng', role: 'engineer' }
    else if (url.startsWith(`/api/devices/${SW.id}`)) body = SW
    else if (url.endsWith('/onvif')) body = cam = { ...CAM, facts: FACTS }
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Devices />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Devices – access points and cameras', () => {
  it('shows an AP as controller-managed and links to its switch port', async () => {
    mockApi([])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /ap-lobby/ }))
    expect(screen.getByText(/Managed by its wireless controller/)).toBeTruthy()
    const link = await screen.findByRole('link', { name: /Configure switch port/ })
    const href = new URL(link.getAttribute('href'), 'http://x')
    expect(href.pathname).toBe('/configure')
    expect(Object.fromEntries(href.searchParams)).toEqual({ device: SW.id, port: 'GigabitEthernet0/5', for: 'ap-lobby' })
    expect(screen.queryByRole('link', { name: /^Configure$/ })).toBeNull() // the AP itself is not configured
  })

  it('reads ONVIF facts and forgets the camera password', async () => {
    const calls = []
    mockApi(calls)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /cam1/ }))
    fireEvent.change(screen.getByLabelText('Camera user'), { target: { value: 'viewer' } })
    fireEvent.change(screen.getByLabelText('Camera password'), { target: { value: 'Cam3ra-Secret' } })
    fireEvent.click(screen.getByRole('button', { name: /Read camera information/ }))
    await waitFor(() => expect(screen.getByText('ACCC8E000001')).toBeTruthy())
    const post = calls.find((c) => c.url.endsWith('/onvif'))
    expect(post.method).toBe('POST')
    expect(JSON.parse(post.body)).toEqual({ username: 'viewer', password: 'Cam3ra-Secret', port: 80 })
    expect(screen.getByLabelText('Camera password').value).toBe('')
    expect(JSON.stringify({ ...localStorage })).not.toContain('Cam3ra-Secret')
  })
})
