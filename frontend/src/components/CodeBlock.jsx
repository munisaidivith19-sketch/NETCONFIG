import { useState } from 'react'
import { Copy } from 'lucide-react'

/** Numbered, copyable block of commands or device output (already masked by the backend). */
export default function CodeBlock({ lines, label, empty = 'Nothing here.' }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="stack">
      <div className="row between">
        <strong>{label}</strong>
        {lines.length > 0 && (
          <button type="button" className="btn small ghost" onClick={copy}>
            <Copy size={16} aria-hidden="true" /> {copied ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>
      {lines.length === 0 ? (
        <p className="faint">{empty}</p>
      ) : (
        <pre className="code" aria-label={label} tabIndex={0}>
          {lines.map((l, i) => (
            <span className="line" key={i}>{l || ' '}</span>
          ))}
        </pre>
      )}
    </div>
  )
}
