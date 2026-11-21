import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AiDraft from './AiDraft.jsx'
import Explain from './Explain.jsx'
import { AuthProvider } from '../lib/auth.jsx'
import { MAX_EXPLAIN_CHARS, onlySupported, resetAiStatus } from '../lib/ai.js'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  resetAiStatus()
})

const json = (body, status = 200) =>
  Promise.resolve({ ok: status < 400, status, text: () => Promise.resolve(JSON.stringify(body)) })

/** Fake backend: role of the logged-in user, AI status, and the answer to POST /api/ai/*. */
function backend({ role = 'engineer', enabled = true, answer = {} } = {}) {
  const calls = []
  globalThis.fetch = vi.fn((url, opts = {}) => {
    calls.push({ url, body: opts.body ? JSON.parse(opts.body) : null })
    if (url.startsWith('/api/auth/me')) return json({ id: '1', username: 'e', role })
    if (url.startsWith('/api/ai/status')) return json({ enabled, provider: enabled ? 'ollama' : null, model: null })
    if (url.startsWith('/api/ai/')) return json(answer)
    return json({ items: [] })
  })
  return calls
}

const wrap = (ui) => render(<MemoryRouter><AuthProvider>{ui}</AuthProvider></MemoryRouter>)

describe('Explain', () => {
  it('shows the answer as plain text, never as HTML', async () => {
    const calls = backend({ answer: { text: '<img src=x onerror="alert(1)"> VLAN 10 is created.' } })
    const { container } = wrap(<Explain kind="commands" text="vlan 10" />)
    fireEvent.click(await screen.findByRole('button', { name: /explain these commands/i }))
    await screen.findByText(/VLAN 10 is created/)
    expect(container.querySelector('img')).toBeNull()
    expect(calls.find((c) => c.url === '/api/ai/explain').body).toEqual({ kind: 'commands', text: 'vlan 10' })
  })

  it('cuts long texts to the backend limit and says so', async () => {
    const calls = backend({ answer: { text: 'ok' } })
    wrap(<Explain kind="diff" text={'x'.repeat(MAX_EXPLAIN_CHARS + 500)} />)
    fireEvent.click(await screen.findByRole('button', { name: /explain the differences/i }))
    await screen.findByText(/only the first part/i)
    expect(calls.find((c) => c.url === '/api/ai/explain').body.text).toHaveLength(MAX_EXPLAIN_CHARS)
  })

  it('is hidden when the assistant is off or the user is a viewer', async () => {
    for (const opts of [{ enabled: false }, { role: 'viewer' }]) {
      const calls = backend(opts)
      wrap(<Explain kind="commands" text="vlan 10" />)
      await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/ai/status'))).toBe(true))
      await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/auth/me'))).toBe(true))
      expect(screen.queryByRole('button', { name: /explain/i })).toBeNull()
      cleanup()
      resetAiStatus()
    }
  })
})

describe('AiDraft', () => {
  it('fills the form only with what the device supports and never pushes', async () => {
    const plan = { vlans: [{ id: 30, name: 'WiFi' }], routing: { ospf: { process_id: 1, router_id: '1.1.1.1' } }, ssh: null }
    const calls = backend({ answer: { plan, features: ['vlans', 'ospf'], dropped: ['ssh'] } })
    const setForm = vi.fn()
    wrap(<AiDraft setForm={setForm} caps={new Set(['vlans', 'access'])} category="switch" />)
    fireEvent.change(await screen.findByLabelText(/requirements in your own words/i), { target: { value: 'Wi-Fi on VLAN 30 with OSPF to the core' } })
    fireEvent.click(screen.getByRole('button', { name: /draft the form/i }))
    await screen.findByText(/AI draft loaded/)
    const form = setForm.mock.calls[0][0]()
    expect(form.vlans).toEqual([{ id: '30', name: 'WiFi' }])
    expect(form.ospf.on).toBeFalsy() // OSPF is not supported on this switch: left out, and the user is told
    expect(screen.getByText(/does not support it: OSPF/)).toBeTruthy()
    expect(screen.getByText(/also suggested an SSH login/)).toBeTruthy()
    expect(calls.every((c) => !c.url.startsWith('/api/jobs'))).toBe(true) // a draft never creates a job
  })
})

describe('onlySupported', () => {
  it('removes unsupported sections and reports them', () => {
    const plan = { vlans: [{ id: 2 }], statics: [{ prefix: '0.0.0.0/0' }], default_gateway: '10.0.0.1', routing: { bgp: { asn: 65000 } } }
    const { plan: out, removed } = onlySupported(plan, ['vlans', 'static', 'default_gateway', 'bgp'], new Set(['vlans', 'static', 'default_gateway']), 'router')
    expect(removed).toEqual(['default_gateway', 'bgp']) // a default gateway is only for an L2 switch
    expect(out.vlans).toHaveLength(1)
    expect(out.statics).toHaveLength(1)
    expect(out.default_gateway).toBeNull()
    expect(out.routing.bgp).toBeNull()
    expect(plan.routing.bgp).toEqual({ asn: 65000 }) // the input is not changed
  })
})
