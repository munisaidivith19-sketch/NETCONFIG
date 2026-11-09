// Form state → request bodies for the router link and first-time setup wizards (POST /jobs/preview, /jobs).
// The backend validates everything again (backend/app/models/wizards.py); this only shapes the JSON.

import { num, text } from './plan.js'

export const emptyLink = () => ({
  a: { device_id: '', interface: '', router_id: '', asn: '' },
  b: { device_id: '', interface: '', router_id: '', asn: '' },
  subnet: '10.255.0.0/30',
  protocol: 'ospf',
  ospf_process_id: '1',
  ospf_area: '0',
  eigrp_asn: '',
  description: '',
  revert_minutes: '10',
})

export function linkBody(f) {
  const end = (e) => {
    const out = { device_id: e.device_id, interface: e.interface.trim() }
    if (f.protocol !== 'none' && text(e.router_id)) out.router_id = text(e.router_id)
    if (f.protocol === 'bgp' && text(e.asn)) out.asn = num(e.asn)
    return out
  }
  const link = {
    a: end(f.a), b: end(f.b), subnet: f.subnet.trim(), protocol: f.protocol,
    revert_minutes: num(f.revert_minutes) ?? 10,
  }
  if (f.protocol === 'ospf') {
    link.ospf_process_id = num(f.ospf_process_id) ?? 1
    link.ospf_area = num(f.ospf_area) ?? 0
  }
  if (f.protocol === 'eigrp' && text(f.eigrp_asn)) link.eigrp_asn = num(f.eigrp_asn)
  if (text(f.description)) link.description = text(f.description)
  return { link }
}

/** The two host addresses of a /30, or both addresses of a /31, for the hint under the subnet field. */
export function linkAddresses(subnet) {
  const m = String(subnet || '').trim().match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(30|31)$/)
  if (!m || m.slice(1, 5).some((o) => Number(o) > 255)) return null
  const base = m.slice(1, 5).reduce((acc, o) => acc * 256 + Number(o), 0)
  const size = m[5] === '31' ? 2 : 4
  if (base % size) return null // host bits set: the backend explains it
  const ip = (n) => [24, 16, 8, 0].map((s) => Math.floor(n / 2 ** s) % 256).join('.')
  return m[5] === '31' ? [ip(base), ip(base + 1)] : [ip(base + 1), ip(base + 2)]
}

export const emptyBootstrap = () => ({
  device_id: '',
  hostname: '',
  domain: '',
  admin_username: '',
  vlan: '1',
  interface: '',
  ip: '',
  gateway: '',
  rsa_modulus: '2048',
  vty_timeout_minutes: '10',
  hardening: true,
  revert_minutes: '10',
})

export function bootstrapBody(f, category) {
  const mgmt = { ip: f.ip.trim() }
  if (category === 'router') mgmt.interface = f.interface.trim()
  else mgmt.vlan = num(f.vlan) ?? 1
  if (text(f.gateway)) mgmt.gateway = text(f.gateway)
  return {
    device_id: f.device_id,
    bootstrap: {
      hostname: f.hostname.trim(), domain: f.domain.trim(), admin_username: f.admin_username.trim(), mgmt,
      rsa_modulus: num(f.rsa_modulus), vty_timeout_minutes: num(f.vty_timeout_minutes) ?? 10,
      hardening: f.hardening, revert_minutes: num(f.revert_minutes) ?? 10,
    },
  }
}
