import { describe, expect, it } from 'vitest'
import { layout } from './TopologyMap.jsx'

const sw = (i) => ({ id: `s${i}`, name: `sw${i}`, category: 'switch' })

describe('TopologyMap layout', () => {
  it('wraps a tier onto more rows at phone width instead of shrinking the nodes', () => {
    const nodes = [{ id: 'r', name: 'rtr', category: 'router' }, ...[1, 2, 3, 4, 5].map(sw)]
    const phone = layout(nodes, 311) // 375 px screen minus the shell and panel padding
    expect(phone.width).toBe(311)
    expect(phone.rows.map((r) => r.length)).toEqual([1, 2, 2, 1])
    for (const p of Object.values(phone.pos)) {
      expect(p.x - 66).toBeGreaterThanOrEqual(0) // every 132 px node fits inside the map
      expect(p.x + 66).toBeLessThanOrEqual(311)
    }
    expect(layout(nodes, 900).rows.map((r) => r.length)).toEqual([1, 5])
  })
})
