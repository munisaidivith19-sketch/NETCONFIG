import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import HostKeys from './HostKeys.jsx'

const PINNED = {
  id: 'a'.repeat(24), host: '10.0.0.2', port: 22, key_type: 'ssh-rsa', fingerprint: 'SHA256:old',
  first_seen: '2026-11-10T10:00:00Z', last_seen: '2026-11-20T10:00:00Z', accepted_by: null, pending: null,
}
const CHANGED = {
  ...PINNED, id: 'b'.repeat(24), host: '10.0.0.3',
  pending: { key_type: 'ssh-ed25519', fingerprint: 'SHA256:new', seen_at: '2026-11-21T10:00:00Z' },
}

function mockApi(calls) {
  let keys = [PINNED, CHANGED]
  globalThis.fetch = vi.fn((url, opts = {}) => {
    const method = opts.method || 'GET'
    calls.push({ url, method, headers: opts.headers })
    let body = keys
    if (method === 'POST' && url.endsWith('/accept')) {
      body = { ...CHANGED, fingerprint: 'SHA256:new', pending: null }
      keys = [PINNED, body]
    }
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SSH host keys', () => {
  it('warns about a changed key and accepts it only after confirming the new fingerprint', async () => {
    const calls = []
    mockApi(calls)
    render(<HostKeys />)
    expect(await screen.findByText('1 device offered a different key.')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Accept new key' })).toHaveLength(1) // only the changed host

    fireEvent.click(screen.getByRole('button', { name: 'Accept new key' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('SHA256:new') // the admin compares this with the device console
    expect(calls.some((c) => c.method === 'POST')).toBe(false) // nothing is accepted before confirming

    fireEvent.click(screen.getAllByRole('button', { name: 'Accept new key' }).at(-1))
    await waitFor(() => expect(screen.queryByText(/offered a different key/)).toBeNull())
    const accept = calls.find((c) => c.method === 'POST')
    expect(accept.url).toBe(`/api/hostkeys/${CHANGED.id}/accept`)
  })

  it('keeps the key when the dialog is dismissed', async () => {
    const calls = []
    mockApi(calls)
    render(<HostKeys />)
    fireEvent.click(await screen.findByRole('button', { name: `Forget the key of ${PINNED.host}:22` }))
    fireEvent.click(await screen.findByRole('button', { name: 'Keep as is' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls.every((c) => c.method === 'GET')).toBe(true)
  })
})
