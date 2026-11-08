import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { get, onUnauthorized, post } from './api.js'

const AuthContext = createContext(null)
const RANK = { viewer: 0, engineer: 1, admin: 2 }

export function AuthProvider({ children }) {
  // undefined = still checking the session, null = signed out
  const [user, setUser] = useState(undefined)
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    let cancelled = false
    get('/auth/me')
      .then((me) => !cancelled && setUser(me))
      .catch(() => !cancelled && setUser(null))
    onUnauthorized(() => {
      setExpired(true)
      setUser(null)
    })
    return () => {
      cancelled = true
      onUnauthorized(null)
    }
  }, [])

  const login = useCallback(async (username, password) => {
    const me = await post('/auth/login', { username, password })
    setExpired(false)
    setUser(me)
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await post('/auth/logout')
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      expired,
      login,
      logout,
      can: (role) => !!user && RANK[user.role] >= RANK[role],
    }),
    [user, expired, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

export function RequireAuth({ children, role = 'viewer' }) {
  const { user, can } = useAuth()
  const location = useLocation()
  if (user === undefined) {
    return (
      <div className="login-page" aria-busy="true">
        <span className="sr-only">Checking your session…</span>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!can(role)) return <Navigate to="/" replace />
  return children
}
