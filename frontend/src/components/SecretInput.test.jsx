import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { SecretInput } from './ui.jsx'

afterEach(cleanup)

describe('SecretInput', () => {
  it('is a password field the browser must not fill from saved logins (CLAUDE.md 8.3)', () => {
    render(<SecretInput aria-label="Device password" value="" onChange={() => {}} />)
    const input = screen.getByLabelText('Device password')
    expect(input.getAttribute('type')).toBe('password')
    // "off" is ignored by Chromium on password fields; "new-password" keeps a saved app password out of it.
    expect(input.getAttribute('autocomplete')).toBe('new-password')
    expect(input.getAttribute('data-lpignore')).toBe('true')
    expect(input.getAttribute('maxlength')).toBe('128')
  })
})
