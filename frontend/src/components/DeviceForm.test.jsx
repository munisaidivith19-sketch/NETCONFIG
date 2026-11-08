import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DeviceForm from './DeviceForm.jsx'
import { AuthProvider } from '../lib/auth.jsx'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('DeviceForm', () => {
  it('never asks for device passwords', async () => {
    globalThis.fetch = vi.fn((url) => {
      const body = url.startsWith('/api/auth/me') ? { id: '1', username: 'e', role: 'engineer' } : { items: [] }
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(body)) })
    })
    const { container } = render(
      <MemoryRouter>
        <AuthProvider>
          <DeviceForm onSubmit={() => {}} />
        </AuthProvider>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByLabelText('Device name')).toBeTruthy())
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByText(/password|secret/i)).toBeNull()
  })
})
