import { useEffect, useId, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BookOpen,
  FlaskConical,
  History,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Moon,
  Network,
  ScrollText,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Users,
  Waypoints,
} from 'lucide-react'
import { get } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { applyTheme, preferredTheme } from '../lib/theme.js'

const MAIN_NAV = [
  { to: '/', label: 'Overview', short: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/devices', label: 'Devices', short: 'Devices', icon: Server },
  { to: '/topology', label: 'Topology', short: 'Map', icon: Waypoints },
  { to: '/configure', label: 'Configure', short: 'Configure', icon: SlidersHorizontal, role: 'engineer' },
  { to: '/catalog', label: 'Catalog', short: 'Catalog', icon: BookOpen },
  { to: '/history', label: 'History', short: 'History', icon: History },
]
const ADMIN_NAV = [
  { to: '/admin/users', label: 'Users', icon: Users },
  { to: '/admin/audit', label: 'Audit log', icon: ScrollText },
  { to: '/admin/host-keys', label: 'SSH host keys', icon: KeyRound },
]

function ThemeToggle() {
  const [theme, setTheme] = useState(preferredTheme)
  useEffect(() => applyTheme(theme), [theme])
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      className="btn ghost icon"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      {theme === 'dark' ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
    </button>
  )
}

function UserMenu({ withAdmin = false }) {
  const { user, logout, can } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const toggle = useRef(null)
  const panelId = useId()
  // A disclosure (button + list of links), not an ARIA menu: Tab moves through the links, Escape closes the
  // panel and puts focus back on the button.
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => {
      if (e.type === 'keydown' && e.key !== 'Escape') return
      if (e.type === 'mousedown' && ref.current?.contains(e.target)) return
      setOpen(false)
      if (e.type === 'keydown') toggle.current?.focus()
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  if (!user) return null
  return (
    <div className="menu" ref={ref}>
      <button
        ref={toggle}
        type="button"
        className="btn ghost"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">
          {user.username.slice(0, 1).toUpperCase()}
        </span>
        <span>{user.username}</span>
      </button>
      {open && (
        <div className="glass strong menu-panel" id={panelId}>
          <div className="menu-head">
            <strong>{user.username}</strong>
            <div className="faint">Role: {user.role}</div>
          </div>
          <NavLink to="/settings" onClick={() => setOpen(false)}>
            <ShieldCheck size={16} aria-hidden="true" /> Security
          </NavLink>
          {/* On phones the sidebar is hidden, so the admin pages are reachable from this menu instead. */}
          {withAdmin && can('admin') &&
            ADMIN_NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} onClick={() => setOpen(false)}>
                <Icon size={16} aria-hidden="true" /> {label}
              </NavLink>
            ))}
          <button type="button" onClick={logout}>
            <LogOut size={16} aria-hidden="true" /> Log out
          </button>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const { can } = useAuth()
  const location = useLocation()
  const mainRef = useRef(null)

  // Move focus to the page content after navigation so screen readers announce the new page.
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
  }, [location.pathname])

  const nav = MAIN_NAV.filter((item) => !item.role || can(item.role))
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <aside className="glass sidebar" aria-label="Main navigation">
          <NavLink to="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              <Network size={22} />
            </span>
            <span>
              <strong>NetConfig Studio</strong>
              <span className="brand-sub">Local · 127.0.0.1</span>
            </span>
          </NavLink>
          <nav className="nav">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end}>
                <Icon size={18} aria-hidden="true" /> {label}
              </NavLink>
            ))}
            {can('admin') && (
              <>
                <div className="nav-section">Admin</div>
                {ADMIN_NAV.map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to}>
                    <Icon size={18} aria-hidden="true" /> {label}
                  </NavLink>
                ))}
              </>
            )}
          </nav>
          <div className="sidebar-footer">
            <div className="row between">
              <UserMenu />
              <ThemeToggle />
            </div>
          </div>
        </aside>

        <main id="main" className="main" ref={mainRef} tabIndex={-1}>
          <div className="row between mobile-only-bar">
            <MobileBar />
          </div>
          <SimulationBanner />
          <Outlet />
        </main>
      </div>

      <nav className="glass strong bottom-nav" aria-label="Main navigation">
        {nav.map(({ to, short, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={20} aria-hidden="true" />
            {short}
          </NavLink>
        ))}
      </nav>
    </>
  )
}

/** SIMULATE_DEVICES=true (development only): make it impossible to mistake a simulated push for a real one. */
function SimulationBanner() {
  const [mode, setMode] = useState(null)
  useEffect(() => {
    get('/health')
      .then((h) => setMode(h?.demo ? 'demo' : h?.simulation ? 'sim' : null))
      .catch(() => setMode(null))
  }, [])
  if (!mode) return null
  return (
    <div className="alert warning sim-banner" role="status">
      <FlaskConical size={18} aria-hidden="true" />
      {mode === 'demo' ? (
        <div>
          <strong>Public demo. </strong>
          Every device here is simulated: nothing is sent to a real network. The real app runs on the engineer’s own
          laptop, inside the network it manages.
        </div>
      ) : (
        <div>
          <strong>Simulation mode. </strong>
          Pushes go to in-memory simulated devices, not the network. Restart without SIMULATE_DEVICES for real pushes.
        </div>
      )}
    </div>
  )
}

function MobileBar() {
  return (
    <>
      <NavLink to="/" className="brand mobile-brand">
        <span className="brand-mark" aria-hidden="true">
          <Network size={20} />
        </span>
        <strong>NetConfig Studio</strong>
      </NavLink>
      <div className="row">
        <ThemeToggle />
        <UserMenu withAdmin />
      </div>
    </>
  )
}
