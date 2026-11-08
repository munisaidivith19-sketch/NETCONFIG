import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, onUnauthorized, post } from './api.js'

function mockFetch(status, body) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)),
  })
  globalThis.fetch = fn
  return fn
}

afterEach(() => {
  vi.restoreAllMocks()
  onUnauthorized(null)
  localStorage.clear()
  sessionStorage.clear()
})

describe('api client', () => {
  it('always sends the custom anti-CSRF header and same-origin credentials', async () => {
    const fetch = mockFetch(200, { ok: true })
    await api('/health')
    await post('/auth/login', { username: 'a', password: 'b' })
    for (const [url, init] of fetch.mock.calls) {
      expect(url.startsWith('/api/')).toBe(true)
      expect(init.headers['X-Requested-With']).toBe('NetConfigStudio')
      expect(init.credentials).toBe('same-origin')
    }
    expect(fetch.mock.calls[1][1].headers['Content-Type']).toBe('application/json')
  })

  it('never writes to browser storage', async () => {
    mockFetch(200, { id: '1', username: 'admin', role: 'admin' })
    await post('/auth/login', { username: 'admin', password: 'secret-password-1' })
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('turns error bodies into ApiError with field errors and request id', async () => {
    mockFetch(422, { error: { code: 'validation_error', message: 'Bad', fields: { 'vlans.0.id': 'too big' }, request_id: 'abc' } })
    const err = await api('/plans/preview', { method: 'POST', body: {} }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.fields['vlans.0.id']).toBe('too big')
    expect(err.requestId).toBe('abc')
  })

  it('calls the 401 handler except for the login and session check', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    mockFetch(401, { error: { message: 'Please sign in.' } })
    await api('/devices').catch(() => {})
    expect(handler).toHaveBeenCalledTimes(1)
    await api('/auth/me').catch(() => {})
    await api('/auth/login', { method: 'POST', body: {} }).catch(() => {})
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('builds query strings and drops empty values', async () => {
    const fetch = mockFetch(200, {})
    await api('/audit', { query: { action: 'auth', user: '', page: 2 } })
    expect(fetch.mock.calls[0][0]).toBe('/api/audit?action=auth&page=2')
  })
})
