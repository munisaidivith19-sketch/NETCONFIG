// API client. Same origin only; the session lives in an httpOnly cookie the page cannot read.
// Every request carries X-Requested-With so the backend can reject cross-site requests.
// Nothing is ever stored in localStorage/sessionStorage.

export const CUSTOM_HEADER = { 'X-Requested-With': 'NetConfigStudio' }

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error?.message || `Request failed (${status})`)
    this.status = status
    this.code = body?.error?.code
    this.fields = body?.error?.fields || {}
    this.requestId = body?.error?.request_id
  }
}

let unauthorizedHandler = null
export function onUnauthorized(handler) {
  unauthorizedHandler = handler
}

const QUIET_401 = new Set(['/auth/login', '/auth/me'])

export async function api(path, { method = 'GET', body, signal, query } = {}) {
  const headers = { ...CUSTOM_HEADER, Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let url = `/api${path}`
  if (query) {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }

  let res
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError') throw err
    throw new ApiError(0, { error: { message: 'Cannot reach the NetConfig Studio backend. Is it running?' } })
  }

  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }
  if (!res.ok) {
    if (res.status === 401 && unauthorizedHandler && !QUIET_401.has(path)) unauthorizedHandler()
    throw new ApiError(res.status, data)
  }
  return data
}

export const get = (path, opts) => api(path, { ...opts, method: 'GET' })
export const post = (path, body, opts) => api(path, { ...opts, method: 'POST', body: body ?? {} })
export const patch = (path, body, opts) => api(path, { ...opts, method: 'PATCH', body })
export const del = (path, opts) => api(path, { ...opts, method: 'DELETE' })
