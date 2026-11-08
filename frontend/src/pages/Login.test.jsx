import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.jsx'
import { AuthProvider } from '../lib/auth.jsx'

function respond(routes) {
  globalThis.fetch = vi.fn((url, init) => {
    const key = `${init?.method || 'GET'} ${url}`
    const [status, body] = routes[key] || [404, { error: { message: 'not found' } }]
    return Promise.resolve({ ok: status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) })
  })
}

function renderApp(path = '/') {
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

describe('login flow', () => {
  it('redirects to the login page when there is no session', async () => {
    respond({ 'GET /api/auth/me': [401, { error: { message: 'Please sign in.' } }] })
    renderApp('/devices')
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeTruthy()
  })

  it('shows the generic error and clears the password on failure', async () => {
    respond({
      'GET /api/auth/me': [401, {}],
      'POST /api/auth/login': [401, { error: { message: 'Wrong username or password, or the account is temporarily locked.' } }],
    })
    renderApp('/')
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'admin' } })
    const password = screen.getByLabelText('Password')
    fireEvent.change(password, { target: { value: 'bad-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByText(/temporarily locked/)).toBeTruthy()
    expect(password.value).toBe('')
  })

  it('signs in and shows the app shell with the user menu', async () => {
    respond({
      'GET /api/auth/me': [401, {}],
      'POST /api/auth/login': [200, { id: '1', username: 'alice', role: 'engineer' }],
    })
    renderApp('/')
    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Quiet-River-Stone-42' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(screen.getAllByText('alice').length).toBeGreaterThan(0))
    expect(screen.queryAllByRole('link', { name: /users/i })).toHaveLength(0) // not an admin
  })
})
