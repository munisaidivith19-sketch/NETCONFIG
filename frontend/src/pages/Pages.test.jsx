// Smoke tests: every page without its own test file renders its heading and its empty state from the API.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, RequireAuth } from '../lib/auth.jsx'
import Account from './Account.jsx'
import Catalog from './Catalog.jsx'
import History from './History.jsx'
import Audit from './admin/Audit.jsx'
import Users from './admin/Users.jsx'

const ADMIN = { id: 'u1', username: 'admin1', role: 'admin' }

function mockApi() {
  globalThis.fetch = vi.fn((url) => {
    let body = { items: [], total: 0 }
    if (url.startsWith('/api/auth/me')) body = ADMIN
    else if (url.startsWith('/api/users')) body = [{ ...ADMIN, disabled: false, created_at: '2026-11-08T10:00:00Z' }]
    else if (url.startsWith('/api/catalog/os-drivers') || url.startsWith('/api/catalog/brands')) body = []
    else if (url.startsWith('/api/audit/verify')) body = { ok: true, first_bad_seq: null }
    return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

function renderAt(element, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          {/* as in App.jsx: every page sits behind the sign-in check */}
          <Route path="/" element={<RequireAuth>{element}</RequireAuth>} />
          <Route path="/history/:jobId?" element={<RequireAuth>{element}</RequireAuth>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe.each([
  ['History', <History key="h" />, '/history'],
  ['Catalog', <Catalog key="c" />, '/'],
  ['Security', <Account key="a" />, '/'],
  ['Audit log', <Audit key="au" />, '/'],
  ['Users', <Users key="u" />, '/'],
])('%s page', (title, element, path) => {
  it('renders without errors', async () => {
    mockApi()
    renderAt(element, path)
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeTruthy()
    expect(screen.queryByText(/something went wrong/i)).toBeNull()
  })
})

it('Settings lets an admin reset another user, but not themselves', async () => {
  mockApi()
  const other = { id: 'u2', username: 'eng1', role: 'engineer', disabled: false, created_at: '2026-11-08T10:00:00Z' }
  const base = globalThis.fetch
  globalThis.fetch = vi.fn((url, opts) => {
    if (url.startsWith('/api/users') && (!opts || !opts.method || opts.method === 'GET')) {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify([ADMIN, other])) })
    }
    return base(url, opts)
  })
  renderAt(<Account />)
  expect(await screen.findByRole('heading', { name: "Reset a user's password" })).toBeTruthy()
  expect(await screen.findByRole('option', { name: 'eng1 (engineer)' })).toBeTruthy()
  expect(screen.queryByRole('option', { name: /admin1/ })).toBeNull()
})

it('Users lists the signed-in admin', async () => {
  mockApi()
  renderAt(<Users />)
  expect(await screen.findByText('admin1')).toBeTruthy()
})
