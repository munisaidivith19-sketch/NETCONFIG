// Line diff of two configs (Myers' O(ND) algorithm). Used to compare a job's backup with the previous backup of
// the same device. Configs are thousands of lines but usually differ in a few, so the common start and end are
// trimmed first and the search gives up after MAX_EDITS changes instead of freezing the page.

const MAX_EDITS = 1500

/** a, b: arrays of lines -> [['=' | '-' | '+', line], ...] or null when they differ in more than maxEdits lines. */
export function diffLines(a, b, maxEdits = MAX_EDITS) {
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB-- }
  const middle = myers(a.slice(start, endA), b.slice(start, endB), maxEdits)
  if (!middle) return null
  return [
    ...a.slice(0, start).map((l) => ['=', l]),
    ...middle,
    ...a.slice(endA).map((l) => ['=', l]),
  ]
}

function myers(a, b, maxD) {
  const n = a.length
  const m = b.length
  const limit = Math.min(n + m, maxD)
  const off = limit + 1
  const v = new Int32Array(2 * limit + 3)
  const trace = [] // trace[d] = v[-d-1 .. d+1] before step d (only the part step d reads: O(D²) memory)
  for (let d = 0; d <= limit; d++) {
    trace.push(v.slice(off - d - 1, off + d + 2))
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[off + k - 1] < v[off + k + 1]) ? v[off + k + 1] : v[off + k - 1] + 1
      let y = x - k
      while (x < n && y < m && a[x] === b[y]) { x++; y++ }
      v[off + k] = x
      if (x >= n && y >= m) return backtrack(trace, a, b)
    }
  }
  return null
}

function backtrack(trace, a, b) {
  const ops = []
  let x = a.length
  let y = b.length
  for (let d = trace.length - 1; d >= 0; d--) {
    const vd = trace[d]
    const at = (k) => vd[k + d + 1]
    const k = x - y
    const prevK = k === -d || (k !== d && at(k - 1) < at(k + 1)) ? k + 1 : k - 1
    const prevX = d === 0 ? 0 : at(prevK)
    const prevY = d === 0 ? 0 : prevX - prevK
    while (x > prevX && y > prevY) { ops.push(['=', a[x - 1]]); x--; y-- }
    if (d > 0) {
      if (x === prevX) ops.push(['+', b[y - 1]])
      else ops.push(['-', a[x - 1]])
    }
    x = prevX
    y = prevY
  }
  return ops.reverse()
}

/** Only the changed lines with `context` lines around them; '…' marks skipped unchanged lines. */
export function unified(ops, context = 2) {
  const keep = new Array(ops.length).fill(false)
  ops.forEach(([op], i) => {
    if (op === '=') return
    for (let j = Math.max(0, i - context); j <= Math.min(ops.length - 1, i + context); j++) keep[j] = true
  })
  const lines = []
  let skipped = false
  ops.forEach(([op, line], i) => {
    if (!keep[i]) { skipped = true; return }
    if (skipped && lines.length) lines.push('…')
    skipped = false
    lines.push(`${op === '=' ? ' ' : op} ${line}`)
  })
  return {
    lines,
    added: ops.filter(([op]) => op === '+').length,
    removed: ops.filter(([op]) => op === '-').length,
  }
}
