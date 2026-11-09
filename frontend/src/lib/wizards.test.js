import { describe, expect, it } from 'vitest'
import { canCancel, deviceNames, needsLogin, phaseStates } from './jobs.js'
import { emptyForm, fromPlan, toPlan } from './plan.js'
import { bootstrapBody, emptyBootstrap, emptyLink, linkAddresses, linkBody } from './wizards.js'

describe('router link body', () => {
  it('sends only the fields the protocol needs', () => {
    const f = emptyLink()
    f.a = { device_id: 'a'.repeat(24), interface: ' Gi0/1 ', router_id: '1.1.1.1', asn: '65001' }
    f.b = { device_id: 'b'.repeat(24), interface: 'Gi0/1', router_id: '2.2.2.2', asn: '65002' }
    expect(linkBody(f).link).toEqual({
      a: { device_id: 'a'.repeat(24), interface: 'Gi0/1', router_id: '1.1.1.1' },
      b: { device_id: 'b'.repeat(24), interface: 'Gi0/1', router_id: '2.2.2.2' },
      subnet: '10.255.0.0/30', protocol: 'ospf', revert_minutes: 10, ospf_process_id: 1, ospf_area: 0,
    })
    f.protocol = 'bgp'
    expect(linkBody(f).link.a.asn).toBe(65001)
    f.protocol = 'none'
    expect(linkBody(f).link.a.router_id).toBeUndefined()
  })

  it('shows the two addresses of a /30 or /31', () => {
    expect(linkAddresses('10.255.0.0/30')).toEqual(['10.255.0.1', '10.255.0.2'])
    expect(linkAddresses('10.255.0.4/31')).toEqual(['10.255.0.4', '10.255.0.5'])
    expect(linkAddresses('10.255.0.1/30')).toBeNull() // host bits set
    expect(linkAddresses('10.255.0.0/29')).toBeNull()
  })
})

describe('bootstrap body', () => {
  it('uses a VLAN for switches and a port for routers', () => {
    const f = { ...emptyBootstrap(), device_id: 'd'.repeat(24), hostname: 'sw9', domain: 'lab.example.net', admin_username: 'netadmin', vlan: '99', interface: 'Gi0/0', ip: '10.0.0.2/24', gateway: '10.0.0.1' }
    expect(bootstrapBody(f, 'switch').bootstrap.mgmt).toEqual({ ip: '10.0.0.2/24', vlan: 99, gateway: '10.0.0.1' })
    expect(bootstrapBody(f, 'router').bootstrap.mgmt).toEqual({ ip: '10.0.0.2/24', interface: 'Gi0/0', gateway: '10.0.0.1' })
  })
})

describe('templates', () => {
  it('turns a plan back into the same form', () => {
    const form = emptyForm()
    form.basic = { on: true, hostname: 'sw1', domain: 'lab.example.net' }
    form.vlans = [{ id: '10', name: 'Sales' }]
    form.access = [{ interfaces: 'Gi1/0/1, Gi1/0/2', vlan: '10', description: '', portfast: true, port_security: false, ps_max: '1', ps_violation: 'shutdown', ps_sticky: false }]
    form.statics = [{ prefix: '0.0.0.0/0', target: '10.0.0.1', distance: '' }]
    form.default_gateway = '10.0.0.1'
    form.custom = 'ntp server 10.0.0.5\nlogging host 10.0.0.6'
    const plan = toPlan(form)
    expect(toPlan(fromPlan(plan))).toEqual(plan)
  })
})

describe('multi-step jobs', () => {
  const step = (status, states, extra = {}) => ({ status, connection: 'ssh', device_name: 'sw', timeline: states.map((state) => ({ state })), ...extra })
  const job = {
    kind: 'multi', status: 'applying',
    steps: [step('success', ['queued', 'connecting', 'backing_up', 'checking', 'applying', 'verifying', 'saving', 'success'], { device_name: 'sw1' }),
      step('applying', ['queued', 'connecting', 'backing_up', 'checking', 'applying'], { device_name: 'sw2', connection: 'serial' })],
  }

  it('shows the phases of the chosen device', () => {
    expect(phaseStates(job, 0).every((p) => p.state === 'done')).toBe(true)
    expect(phaseStates(job, 1).find((p) => p.id === 'applying').state).toBe('active')
  })

  it('knows the login and cancel rules', () => {
    expect(needsLogin(job)).toBe(true)
    expect(needsLogin({ steps: [{ connection: 'serial' }] })).toBe(false)
    expect(canCancel(job)).toBe(true) // several switches: stop before the next one
    expect(canCancel({ ...job, kind: 'link' })).toBe(false)
    expect(deviceNames(job)).toBe('sw1, sw2')
    expect(deviceNames({ ...job, kind: 'link' })).toBe('sw1 ↔ sw2')
  })
})
