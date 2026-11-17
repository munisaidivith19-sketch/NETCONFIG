// Network map from the Overview API: routers on top, then L3 switches, switches, and access points / cameras.
// Keyboard: the map is one Tab stop (roving tabindex); arrow keys, Home and End move between nodes, Enter or Space
// selects. Status is a coloured dot plus text ("down", "not checked"), never colour alone, and the links are also
// listed as text for screen readers. The map draws at the width of its panel (1:1), and a
// tier that does not fit wraps onto another row, so nodes stay 132 x 46 px (bigger than a 44 px touch target) and
// labels stay readable on a 375 px phone.
import { useMemo, useRef, useState } from 'react'
import { categoryLabel } from '../lib/labels.js'
import { useWidth } from '../lib/useWidth.js'

const TIERS = [['router'], ['l3switch'], ['switch'], ['ap', 'camera', 'unmanaged']]
const NODE_W = 132
const NODE_H = 46
const ROW_H = 96
const GAP = 12

function tierOf(node) {
  if (node.external) return 0
  const t = TIERS.findIndex((cats) => cats.includes(node.category))
  return t < 0 ? TIERS.length - 1 : t
}

export function layout(nodes, width = 760) {
  const tiers = TIERS.map(() => [])
  nodes.forEach((n) => tiers[tierOf(n)].push(n))
  const fit = Math.max(1, Math.floor((width - GAP) / (NODE_W + GAP)))
  const rows = []
  tiers.filter((t) => t.length).forEach((tier) => {
    tier.sort((a, b) => Number(a.external) - Number(b.external) || a.name.localeCompare(b.name))
    for (let i = 0; i < tier.length; i += fit) rows.push(tier.slice(i, i + fit))
  })
  const pos = {}
  rows.forEach((row, ri) => {
    const gap = width / row.length
    row.forEach((n, i) => { pos[n.id] = { x: gap * i + gap / 2, y: 20 + ri * ROW_H + NODE_H / 2, row: ri, col: i } })
  })
  return { pos, rows, width, height: rows.length * ROW_H - ROW_H + NODE_H + 40 }
}

const statusText = (n) => (n.external ? 'not in inventory' : n.reachable === true ? 'up' : n.reachable === false ? 'down' : 'not checked')
const statusClass = (n) => (n.reachable === true ? 'up' : n.reachable === false ? 'down' : 'unknown')

export default function TopologyMap({ nodes, links, selectedId, onSelect }) {
  const [box, measured] = useWidth(760)
  const { pos, rows, width, height } = useMemo(() => layout(nodes, measured), [nodes, measured])
  const refs = useRef({})
  const [focusId, setFocusId] = useState(null)
  const names = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.name])), [nodes])
  const downIds = useMemo(() => new Set(nodes.filter((n) => n.reachable === false).map((n) => n.id)), [nodes])
  // The one node in the Tab order: the last focused, else the selected one, else the first.
  const tabId = [focusId, selectedId].find((id) => id && pos[id]) || rows[0]?.[0]?.id

  function move(e, node) {
    const p = pos[node.id]
    let target = null
    if (e.key === 'Home') target = rows[0][0]
    if (e.key === 'End') target = rows[rows.length - 1].at(-1)
    if (e.key === 'ArrowRight') target = rows[p.row][p.col + 1]
    if (e.key === 'ArrowLeft') target = rows[p.row][p.col - 1]
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const row = rows[p.row + (e.key === 'ArrowDown' ? 1 : -1)]
      if (row) target = row[Math.min(row.length - 1, Math.round((p.col / Math.max(1, rows[p.row].length - 1)) * (row.length - 1)))]
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (!node.external) onSelect(node.id)
      return
    }
    if (target) {
      e.preventDefault()
      refs.current[target.id]?.focus()
    }
  }

  return (
    <div ref={box}>
      <svg className="topology" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="group"
        aria-label={`Network map: ${nodes.length} devices and ${links.length} links. Use the arrow keys to move between devices.`}>
        {links.map((l, i) => {
          const a = pos[l.a]
          const b = pos[l.b]
          if (!a || !b) return null
          const down = downIds.has(l.a) || downIds.has(l.b)
          return (
            <line key={i} className={`link ${l.source === 'uplink' ? '' : 'trunk'} ${down ? 'down' : ''}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}>
              <title>{`${l.a_port || '?'} ↔ ${l.b_port || '?'} (${l.source})`}</title>
            </line>
          )
        })}
        {nodes.map((n) => {
          const p = pos[n.id]
          return (
            <g key={n.id} ref={(el) => { refs.current[n.id] = el }}
              className={`node ${selectedId === n.id ? 'selected' : ''} ${n.external ? 'external' : ''}`}
              transform={`translate(${p.x - NODE_W / 2} ${p.y - NODE_H / 2})`}
              tabIndex={n.id === tabId ? 0 : -1} onFocus={() => setFocusId(n.id)}
            role="button" aria-pressed={n.external ? undefined : selectedId === n.id} aria-disabled={n.external || undefined}
              aria-label={`${n.name}, ${n.external ? 'neighbour outside the inventory' : categoryLabel(n.category)}, ${statusText(n)}`}
              onClick={() => !n.external && onSelect(n.id)} onKeyDown={(e) => move(e, n)}>
              <rect className="node-bg" width={NODE_W} height={NODE_H} rx="14" />
              <circle className={`status ${statusClass(n)}`} cx="14" cy={NODE_H / 2} r="5" />
              <text className="node-label" x="26" y="20">{n.name.length > 13 ? `${n.name.slice(0, 12)}…` : n.name}</text>
              <text className="node-sub" x="26" y="35">{n.external ? 'external' : n.reachable === true ? (n.model_name || '').slice(0, 15) : statusText(n)}</text>
            </g>
          )
        })}
      </svg>
      {links.length > 0 && (
        <ul className="sr-only" aria-label="Links">
          {links.map((l, i) => (
            <li key={i}>{`${names[l.a] || l.a} ${l.a_port || ''} to ${names[l.b] || l.b} ${l.b_port || ''} (${l.source})`}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
