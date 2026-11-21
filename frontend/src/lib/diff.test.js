import { describe, expect, it } from 'vitest'
import { diffLines, unified } from './diff.js'

const apply = (ops) => ({
  before: ops.filter(([op]) => op !== '+').map(([, l]) => l),
  after: ops.filter(([op]) => op !== '-').map(([, l]) => l),
})

describe('diffLines', () => {
  it('finds added, removed and changed lines and rebuilds both sides', () => {
    const a = ['hostname sw1', 'vlan 10', ' name Sales', 'interface Gi0/1', ' shutdown', 'end']
    const b = ['hostname sw1', 'vlan 10', ' name Sales', 'vlan 30', ' name WiFi', 'interface Gi0/1', ' no shutdown', 'end']
    const ops = diffLines(a, b)
    expect(apply(ops)).toEqual({ before: a, after: b })
    expect(ops.filter(([op]) => op === '+').map(([, l]) => l)).toEqual(['vlan 30', ' name WiFi', ' no shutdown'])
    expect(ops.filter(([op]) => op === '-').map(([, l]) => l)).toEqual([' shutdown'])
  })

  it('handles empty and identical inputs', () => {
    expect(diffLines([], [])).toEqual([])
    expect(diffLines(['a'], ['a'])).toEqual([['=', 'a']])
    expect(diffLines([], ['a', 'b'])).toEqual([['+', 'a'], ['+', 'b']])
    expect(diffLines(['a', 'b'], [])).toEqual([['-', 'a'], ['-', 'b']])
  })

  it('stays correct on random edits', () => {
    let seed = 7
    const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n }
    for (let t = 0; t < 50; t++) {
      const a = Array.from({ length: rnd(30) }, () => `l${rnd(6)}`)
      const b = Array.from({ length: rnd(30) }, () => `l${rnd(6)}`)
      expect(apply(diffLines(a, b))).toEqual({ before: a, after: b })
    }
  })

  it('gives up instead of freezing on configs that differ everywhere', () => {
    const a = Array.from({ length: 3000 }, (_, i) => `a${i}`)
    const b = Array.from({ length: 3000 }, (_, i) => `b${i}`)
    expect(diffLines(a, b, 100)).toBeNull()
  })
})

describe('unified', () => {
  it('keeps only the changes with context and marks skipped lines', () => {
    const a = Array.from({ length: 20 }, (_, i) => `line ${i}`)
    const b = [...a]
    b[2] = 'changed 2'
    b[15] = 'changed 15'
    const { lines, added, removed } = unified(diffLines(a, b), 1)
    expect(added).toBe(2)
    expect(removed).toBe(2)
    expect(lines).toContain('- line 2')
    expect(lines).toContain('+ changed 15')
    expect(lines).toContain('…')
    expect(lines).not.toContain('  line 9')
  })
})
