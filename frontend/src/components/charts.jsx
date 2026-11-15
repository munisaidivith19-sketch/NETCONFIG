// Small SVG charts for the Overview (no chart library). Rules from the dataviz skill: thin marks with 4px
// rounded data ends, a 2px surface gap between stacked segments, recessive hairline grid, a legend for 2+
// series, a hover/focus tooltip that never gates (every value is also in the table view), text in text tokens.
import { useId, useState } from 'react'
import { Table2 } from 'lucide-react'

const W = 640

function niceMax(v) {
  if (v <= 4) return 4
  const step = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / step) * step
}

const ticks = (max) => [0, max / 2, max].map((t) => Math.round(t))
const fmtDay = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

// A rect with 4px rounded top corners and a square base (the data end is rounded, the baseline is not).
function topRounded(x, y, w, h, r = 4) {
  const rr = Math.min(r, h, w / 2)
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

export function Legend({ series }) {
  return (
    <div className="legend" aria-hidden="true">
      {series.map((s) => (
        <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  )
}

function Tooltip({ tip }) {
  if (!tip) return null
  return (
    <div className="chart-tip glass strong" role="status" style={{ left: `${tip.left}%`, top: tip.top }}>
      <div className="faint">{tip.title}</div>
      {tip.rows.map((r) => (
        <div key={r.label} className="chart-tip-row">
          {r.color && <i style={{ background: r.color }} aria-hidden="true" />}
          <strong>{r.value}</strong> <span className="muted">{r.label}</span>
        </div>
      ))}
    </div>
  )
}

export function TableToggle({ caption, columns, rows }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className="chart-table">
      <button type="button" className="btn ghost small" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Table2 size={14} aria-hidden="true" /> {open ? 'Hide table' : 'Show as table'}
      </button>
      {open && (
        <div className="table-wrap" id={id}>
          <table>
            <caption className="sr-only">{caption}</caption>
            <thead><tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Stacked columns per day. series: [{ key, label, color }]; extra: keys shown only in tooltip/table. */
export function StackedColumns({ data, series, extra = [], label, height = 180 }) {
  const [tip, setTip] = useState(null)
  const top = 12
  const bottom = 26
  const left = 28
  const plotH = height - top - bottom
  const max = niceMax(Math.max(1, ...data.map((d) => series.reduce((s, x) => s + d[x.key], 0))))
  const band = (W - left) / data.length
  const barW = Math.min(24, band * 0.6)
  const y = (v) => top + plotH - (v / max) * plotH

  function show(d, i) {
    setTip({
      left: ((left + band * i + band / 2) / W) * 100, top: 0, title: fmtDay(d.date),
      rows: [...series.map((s) => ({ label: s.label, value: d[s.key], color: s.color })),
        ...extra.map((e) => ({ label: e.label, value: d[e.key] }))],
    })
  }

  return (
    <div className="chart-wrap" onPointerLeave={() => setTip(null)}>
      <Legend series={series} />
      <svg className="chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label}>
        {ticks(max).map((t) => (
          <g key={t}>
            <line className="grid-line" x1={left} x2={W} y1={y(t)} y2={y(t)} />
            <text className="axis-label" x={left - 6} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = left + band * i + (band - barW) / 2
          let base = 0
          const segs = series.map((s, si) => {
            const v = d[s.key]
            if (!v) return null
            const y0 = y(base)
            base += v
            const y1 = y(base)
            const isTop = series.slice(si + 1).every((n) => !d[n.key])
            const h = Math.max(1, y0 - y1 - (base > v ? 2 : 0)) // 2px surface gap between segments
            return isTop
              ? <path key={s.key} d={topRounded(x, y1, barW, h)} fill={s.color} />
              : <rect key={s.key} x={x} y={y1} width={barW} height={h} fill={s.color} />
          })
          const total = series.reduce((s, x2) => s + d[x2.key], 0)
          return (
            <g key={d.date} className="chart-hit" tabIndex={0} role="img"
              aria-label={`${fmtDay(d.date)}: ${series.map((s) => `${d[s.key]} ${s.label}`).join(', ')}`}
              onPointerEnter={() => show(d, i)} onFocus={() => show(d, i)} onBlur={() => setTip(null)}>
              <rect x={left + band * i} y={top} width={band} height={plotH} fill="transparent" />
              {segs}
              {total === 0 && <line x1={x} x2={x + barW} y1={y(0)} y2={y(0)} className="grid-line" />}
              {(i % Math.ceil(data.length / 7) === 0 || i === data.length - 1) && (
                <text className="axis-label" x={left + band * i + band / 2} y={height - 8} textAnchor="middle">{fmtDay(d.date)}</text>
              )}
            </g>
          )
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  )
}

/** One series over time with a crosshair. points: [{ at, value }]. */
export function TrendLine({ points, label, valueLabel, max: givenMax, height = 160 }) {
  const [idx, setIdx] = useState(null)
  const top = 12
  const bottom = 24
  const left = 28
  const plotH = height - top - bottom
  const max = niceMax(Math.max(1, givenMax || 0, ...points.map((p) => p.value)))
  const x = (i) => left + (points.length < 2 ? (W - left) / 2 : (i / (points.length - 1)) * (W - left - 4))
  const y = (v) => top + plotH - (v / max) * plotH
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join('')
  const area = points.length ? `${path}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z` : ''
  const time = (at) => new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

  function nearest(e) {
    const box = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - box.left) / box.width) * W
    let best = 0
    points.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i })
    setIdx(best)
  }
  function onKey(e) {
    if (!points.length) return
    if (e.key === 'ArrowRight') { e.preventDefault(); setIdx((i) => Math.min(points.length - 1, (i ?? -1) + 1)) }
    if (e.key === 'ArrowLeft') { e.preventDefault(); setIdx((i) => Math.max(0, (i ?? points.length) - 1)) }
  }
  const p = idx !== null ? points[idx] : null
  const last = points[points.length - 1]

  return (
    <div className="chart-wrap" onPointerLeave={() => setIdx(null)}>
      <svg className="chart" viewBox={`0 0 ${W} ${height}`} role="img" tabIndex={0} aria-label={`${label}. Use the arrow keys to read values.`}
        onPointerMove={nearest} onKeyDown={onKey} onBlur={() => setIdx(null)}>
        {ticks(max).map((t) => (
          <g key={t}>
            <line className="grid-line" x1={left} x2={W} y1={y(t)} y2={y(t)} />
            <text className="axis-label" x={left - 6} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        <path d={area} fill="var(--chart-1)" opacity="0.1" />
        <path d={path} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {points.length > 0 && (
          <>
            <text className="axis-label" x={x(0)} y={height - 6}>{time(points[0].at)}</text>
            <text className="axis-label" x={x(points.length - 1)} y={height - 6} textAnchor="end">{time(last.at)}</text>
            <circle cx={x(points.length - 1)} cy={y(last.value)} r="4" fill="var(--chart-1)" stroke="var(--chart-gap)" strokeWidth="2" />
          </>
        )}
        {p && (
          <>
            <line x1={x(idx)} x2={x(idx)} y1={top} y2={top + plotH} stroke="var(--text-faint)" strokeWidth="1" />
            <circle cx={x(idx)} cy={y(p.value)} r="4" fill="var(--chart-1)" stroke="var(--chart-gap)" strokeWidth="2" />
          </>
        )}
      </svg>
      {p && <Tooltip tip={{ left: (x(idx) / W) * 100, top: 0, title: time(p.at), rows: [{ label: valueLabel, value: p.value, color: 'var(--chart-1)' }] }} />}
    </div>
  )
}

/** Horizontal bars, one series, value at the tip. items: [{ label, value }]. */
export function BarList({ items, label }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className="bar-list" aria-label={label}>
      {items.map((i) => (
        <li key={i.label}>
          <span className="bar-list-label">{i.label}</span>
          <span className="bar-list-track" aria-hidden="true">
            <span style={{ width: `${(i.value / max) * 100}%` }} />
          </span>
          <span className="bar-list-value">{i.value}</span>
        </li>
      ))}
    </ul>
  )
}
