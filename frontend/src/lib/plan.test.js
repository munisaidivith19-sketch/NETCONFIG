import { describe, expect, it } from 'vitest'
import { emptyForm, errorAt, normalizeErrors, parsePorts, parseRanges, parseVlans, sectionOf, toPlan } from './plan.js'

describe('plan helpers', () => {
  it('expands port ranges and lists', () => {
    expect(parsePorts('Gi1/0/1-3, Gi1/0/10')).toEqual(['Gi1/0/1', 'Gi1/0/2', 'Gi1/0/3', 'Gi1/0/10'])
    expect(parsePorts('Te1/1/1')).toEqual(['Te1/1/1'])
    expect(parsePorts('')).toEqual([])
  })

  it('expands VLAN lists and passes junk on for the server to reject', () => {
    expect(parseVlans('10,20,30-32')).toEqual([10, 20, 30, 31, 32])
    expect(parseVlans('10 x')).toEqual([10, 'x'])
  })

  it('parses DHCP excluded ranges', () => {
    expect(parseRanges('10.0.0.1-10.0.0.9, 10.0.0.254')).toEqual([{ start: '10.0.0.1', end: '10.0.0.9' }, { start: '10.0.0.254' }])
  })

  it('builds a plan without any secret fields', () => {
    const f = emptyForm()
    f.basic = { on: true, hostname: ' sw1 ', domain: '' }
    f.ssh = { ...f.ssh, on: true, username: 'netadmin' }
    f.vlans = [{ id: '10', name: 'Sales' }]
    f.statics = [{ prefix: '0.0.0.0/0', target: '10.0.0.1', distance: '' }, { prefix: '10.9.0.0/16', target: 'Gi0/1', distance: '5' }]
    f.custom = 'cdp run\n\n  lldp run  \n'
    const plan = toPlan(f)
    expect(plan.basic).toEqual({ hostname: 'sw1', domain: null })
    expect(plan.ssh).not.toHaveProperty('password')
    expect(plan.vlans).toEqual([{ id: 10, name: 'Sales' }])
    expect(plan.statics[0]).toEqual({ prefix: '0.0.0.0/0', distance: null, next_hop: '10.0.0.1' })
    expect(plan.statics[1]).toEqual({ prefix: '10.9.0.0/16', distance: 5, interface: 'Gi0/1' })
    expect(plan.custom_commands).toEqual(['cdp run', '  lldp run'])
    expect(plan).not.toHaveProperty('routing')
    expect(plan).not.toHaveProperty('nat')
  })

  it('maps server error paths', () => {
    const errors = normalizeErrors({ 'plan.vlans.0.id': 'bad', 'access.0.interfaces.2': 'not a port' })
    expect(errors).toEqual({ 'vlans.0.id': 'bad', 'access.0.interfaces.2': 'not a port' })
    expect(errorAt(errors, 'access.0.interfaces')).toBe('not a port')
    expect(errorAt(errors, 'vlans.1.id')).toBeUndefined()
    expect(sectionOf('routing.bgp.neighbors.0.ip')).toBe('bgp')
    expect(sectionOf('custom_commands.1')).toBe('custom')
  })
})
