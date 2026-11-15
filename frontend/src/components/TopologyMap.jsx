// Network map from the Overview API: routers on top, then L3 switches, switches, and access points / cameras.
// Every node is a focusable button: arrow keys move between nodes, Enter or Space selects. Status is a coloured
// dot plus text ("down", "not checked"), never colour alone.
import { useMemo, useRef } from 'react'
import { categoryLabel } from '../lib/labels.js'

const TIERS = [['router'], ['l3switch'], ['switch'], ['ap', 'camera', 'unmanaged']]
const NODE_W = 118
const NODE_H = 46
const ROW_H = 104
const W = 760

function tierOf(node) {
  if (node.external) return 0
  const t = TIERS.findIndex((cats) => cats.includes(node.category))
  return t < 0 ? TIERS.length - 1 : t
}

export function layout(nodes) {
  const rows = TIERS.map(() => [])
  nodes.forEach((n) => rows[tierOf(n)].push(n))
  const used = rows.filter((r) => r.length)
  const perRow = Math.max(1, ...used.map((r) => r.length))
  const width = Math.max(W, perRow * (NODE_W + 16) + 16)
  const pos = {}
  used.forEach((row, ri) => {
    row.sort((a, b) => Number(a.external) - Number(b.external) || a.name.localeCompare(b.name))
    const gap = width / row.length
    row.forEach((n, i) => { pos[n.id] = { x: gap * i + gap / 2, y: 30 + ri * ROW_H + NODE_H / 2, row: ri, col: i } })
  })
  return { pos, rows: used, width, height: used.length * ROW_H + 20 }
}

const statusText = (n) => (n.external ? 'not in inventory' : n.reachable === true ? 'up' : n.reachable === false ? 'down' : 'not checked')
const statusClass = (n) => (n.reachable === true ? 'up' : n.reachable === false ? 'down' : 'unknown')

export default function TopologyMap({ nodes, links, selectedId, onSelect }) {
  const { pos, rows, width, height } = useMemo(() => layout(nodes), [nodes])
  const refs = useRef({})

  function move(e, node) {
    const p = pos[node.id]
    let target = null
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
    <svg className="topology" viewBox={`0 0 ${width} ${height}`} role="group"
      aria-label={`Network map: ${nodes.length} devices and ${links.length} links. Use the arrow keys to move between devices.`}>
      {links.map((l, i) => {
        const a = pos[l.a]
        const b = pos[l.b]
        if (!a || !b) return null
        const down = [l.a, l.b].some((id) => nodes.find((n) => n.id === id)?.reachable === false)
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
            tabIndex={0} role="button" aria-pressed={n.external ? undefined : selectedId === n.id}
            aria-label={`${n.name}, ${n.external ? 'neighbour outside the inventory' : categoryLabel(n.category)}, ${statusText(n)}`}
            onClick={() => !n.external && onSelect(n.id)} onKeyDown={(e) => move(e, n)}>
            <rect className="node-bg" width={NODE_W} height={NODE_H} rx="14" />
            <circle className={`status ${statusClass(n)}`} cx="14" cy={NODE_H / 2} r="5" />
            <text className="node-label" x="26" y="20">{n.name.length > 13 ? `${n.name.slice(0, 12)}…` : n.name}</text>
            <text className="node-sub" x="26" y="35">{n.external ? 'not in inventory' : n.reachable === true ? (n.model_name || '').slice(0, 15) : statusText(n)}</text>
          </g>
        )
      })}
    </svg>
  )
}
