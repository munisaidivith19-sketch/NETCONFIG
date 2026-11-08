import { useEffect, useId, useRef } from 'react'
import { AlertTriangle, CheckCircle2, Info, OctagonAlert } from 'lucide-react'

export function PageHeader({ title, subtitle, children }) {
  return (
    <header className="topbar">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="topbar-actions">{children}</div>}
    </header>
  )
}

export function Panel({ title, subtitle, actions, children, className = '', as: Tag = 'section', ...rest }) {
  const id = useId()
  return (
    <Tag className={`glass panel ${className}`} aria-labelledby={title ? id : undefined} {...rest}>
      {(title || actions) && (
        <div className="panel-header">
          <div>
            {title && <h2 id={id}>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}

const TONES = {
  success: 'success', ok: 'success', up: 'success', tested: 'success',
  warning: 'warning', experimental: 'warning', awaiting_approval: 'warning', ready: 'info',
  danger: 'danger', failed: 'danger', down: 'danger', blocked: 'danger', denied: 'danger',
  info: 'info', planned: 'info', running: 'info',
}

export function Badge({ tone, children, dot = false }) {
  const cls = TONES[tone] || tone || ''
  return (
    <span className={`badge ${cls}`}>
      {dot && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  )
}

export function Field({ label, hint, error, children, id: givenId }) {
  const autoId = useId()
  const id = givenId || autoId
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  const child =
    typeof children === 'function'
      ? children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? 'true' : undefined })
      : children
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {child}
      {hint && !error && (
        <span className="hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  )
}

const ALERT_ICONS = { info: Info, warning: AlertTriangle, danger: OctagonAlert, success: CheckCircle2 }

export function Alert({ tone = 'info', title, children }) {
  const Icon = ALERT_ICONS[tone] || Info
  return (
    <div className={`alert ${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon size={18} aria-hidden="true" />
      <div>
        {title && <strong>{title} </strong>}
        {children}
      </div>
    </div>
  )
}

export function Empty({ icon: Icon, title, children, action }) {
  return (
    <div className="empty">
      {Icon && <Icon size={36} aria-hidden="true" />}
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Skeleton({ height = 16, width = '100%' }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />
}

export function SkeletonRows({ rows = 4 }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={36} />
      ))}
    </div>
  )
}

export function Dialog({ title, onClose, children, labelledBy }) {
  const ref = useRef(null)
  const titleId = useId()
  useEffect(() => {
    const previous = document.activeElement
    const node = ref.current
    const focusables = () =>
      node.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    focusables()[0]?.focus()
    function onKey(e) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab') {
        const list = Array.from(focusables()).filter((el) => !el.disabled)
        if (!list.length) return
        const first = list[0]
        const last = list[list.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    node.addEventListener('keydown', onKey)
    return () => {
      node.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [onClose])
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="glass strong dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy || titleId}
      >
        {title && <h2 id={titleId}>{title}</h2>}
        {children}
      </div>
    </div>
  )
}

export function ErrorNote({ error }) {
  if (!error) return null
  return (
    <Alert tone="danger">
      {error.message}
      {error.requestId && <span className="faint"> (request {error.requestId})</span>}
    </Alert>
  )
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
