// Wizard form state ↔ ConfigPlan request body. The backend validates everything again: these helpers
// only turn the comma-separated inputs into lists. No secrets are part of the form; plan secrets
// (the new local user's password, enable secret) are asked for when the job runs (Phase 3A).

export const emptyForm = () => ({
  basic: { on: false, hostname: '', domain: '' },
  ssh: { on: false, username: '', rsa_modulus: '2048', vty_timeout_minutes: '10', set_enable_secret: false, regenerate_keys: false },
  hardening: { on: false, password_encryption: true, disable_http: true, login_block: true, banner: '' },
  vlans: [],
  access: [],
  trunks: [],
  svis: [],
  interfaces: [],
  dhcp: [],
  nat: { on: false, inside: '', outside: '', networks: '' },
  statics: [],
  default_gateway: '',
  ospf: { on: false, process_id: '1', router_id: '', interfaces: [], passive: '' },
  eigrp: { on: false, asn: '', router_id: '', networks: '', passive: '' },
  bgp: { on: false, asn: '', router_id: '', neighbors: [], networks: '' },
  custom: '',
  save: true,
  revert_minutes: '10',
})

export const NEW_ROWS = {
  vlans: () => ({ id: '', name: '' }),
  access: () => ({ interfaces: '', vlan: '', description: '', portfast: true, port_security: false, ps_max: '1', ps_violation: 'shutdown', ps_sticky: false }),
  trunks: () => ({ interface: '', allowed: '', native: '1', description: '' }),
  svis: () => ({ vlan: '', ip: '', description: '' }),
  interfaces: () => ({ interface: '', ip: '', description: '' }),
  dhcp: () => ({ name: '', network: '', default_router: '', dns: '', domain: '', lease_days: '1', excluded: '' }),
  statics: () => ({ prefix: '', target: '', distance: '' }),
  ospfInterfaces: () => ({ interface: '', area: '0' }),
  bgpNeighbors: () => ({ ip: '', remote_as: '', description: '' }),
}

const split = (text) =>
  String(text || '')
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)

export const num = (v) => {
  const s = String(v ?? '').trim()
  return s === '' ? null : /^\d+$/.test(s) ? Number(s) : s // non-numbers go to the server and fail there
}

export const text = (v) => {
  const s = String(v ?? '').trim()
  return s === '' ? null : s
}

/** A copy of `obj` with the value at a dotted path ("a.device_id", "vlans.0.name") replaced. */
export function setPath(obj, path, value) {
  const next = structuredClone(obj)
  const keys = path.split('.')
  let o = next
  for (const k of keys.slice(0, -1)) o = o[k]
  o[keys.at(-1)] = value
  return next
}

/** "Gi1/0/1-4, Gi1/0/10" → ["Gi1/0/1", "Gi1/0/2", "Gi1/0/3", "Gi1/0/4", "Gi1/0/10"] */
export function parsePorts(input) {
  const out = []
  for (const item of String(input || '').split(',').map((s) => s.trim()).filter(Boolean)) {
    const m = item.match(/^(.*?)(\d+)\s*-\s*(\d+)$/)
    if (m && Number(m[3]) >= Number(m[2]) && Number(m[3]) - Number(m[2]) < 96) {
      for (let n = Number(m[2]); n <= Number(m[3]); n += 1) out.push(`${m[1]}${n}`)
    } else {
      out.push(item.replace(/\s+/g, ''))
    }
  }
  return out
}

/** "10,20,30-32" → [10, 20, 30, 31, 32]. Values that are not numbers are passed on for the server to reject. */
export function parseVlans(input) {
  const out = []
  for (const item of split(String(input || '').replace(/,/g, ' '))) {
    const m = item.match(/^(\d+)-(\d+)$/)
    if (m && Number(m[2]) >= Number(m[1]) && Number(m[2]) - Number(m[1]) < 4094) {
      for (let n = Number(m[1]); n <= Number(m[2]); n += 1) out.push(n)
    } else {
      out.push(num(item))
    }
  }
  return out
}

/** "10.0.0.1-10.0.0.9, 10.0.0.254" → [{start, end}, {start}] */
export function parseRanges(input) {
  return String(input || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((item) => {
      const [start, end] = item.split('-').map((s) => s.trim())
      return end ? { start, end } : { start }
    })
}

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/

export function toPlan(form) {
  const plan = { save: form.save, revert_minutes: num(form.revert_minutes) ?? 10 }
  if (form.basic.on) plan.basic = { hostname: form.basic.hostname.trim(), domain: text(form.basic.domain) }
  if (form.ssh.on) {
    plan.ssh = {
      username: form.ssh.username.trim(),
      rsa_modulus: num(form.ssh.rsa_modulus),
      vty_timeout_minutes: num(form.ssh.vty_timeout_minutes),
      set_enable_secret: form.ssh.set_enable_secret,
      regenerate_keys: form.ssh.regenerate_keys,
    }
  }
  if (form.hardening.on) {
    const h = form.hardening
    plan.hardening = {
      password_encryption: h.password_encryption,
      disable_http: h.disable_http,
      login_block: h.login_block ? {} : null,
      banner: text(h.banner),
    }
  }
  plan.vlans = form.vlans.map((v) => ({ id: num(v.id), name: v.name.trim() }))
  plan.access = form.access.map((a) => ({
    interfaces: parsePorts(a.interfaces),
    vlan: num(a.vlan),
    description: text(a.description),
    portfast: a.portfast,
    port_security: a.port_security ? { maximum: num(a.ps_max) ?? 1, violation: a.ps_violation, sticky: a.ps_sticky } : null,
  }))
  plan.trunks = form.trunks.map((t) => ({
    interface: t.interface.trim(),
    allowed_vlans: parseVlans(t.allowed),
    native_vlan: num(t.native) ?? 1,
    description: text(t.description),
  }))
  plan.svis = form.svis.map((s) => ({ vlan: num(s.vlan), ip: s.ip.trim(), description: text(s.description) }))
  plan.interfaces = form.interfaces.map((i) => ({ interface: i.interface.trim(), ip: i.ip.trim(), description: text(i.description) }))
  plan.dhcp = form.dhcp.map((d) => ({
    name: d.name.trim(),
    network: d.network.trim(),
    default_router: d.default_router.trim(),
    dns_servers: split(d.dns),
    domain: text(d.domain),
    lease_days: num(d.lease_days) ?? 1,
    excluded: parseRanges(d.excluded),
  }))
  if (form.nat.on) {
    plan.nat = {
      inside_interfaces: parsePorts(form.nat.inside),
      outside_interface: form.nat.outside.trim(),
      inside_networks: split(form.nat.networks),
    }
  }
  plan.statics = form.statics.map((s) => {
    const target = s.target.trim()
    const route = { prefix: s.prefix.trim(), distance: num(s.distance) }
    return IPV4.test(target) ? { ...route, next_hop: target } : { ...route, interface: target }
  })
  if (text(form.default_gateway)) plan.default_gateway = text(form.default_gateway)
  const routing = {}
  if (form.ospf.on) {
    routing.ospf = {
      process_id: num(form.ospf.process_id) ?? 1,
      router_id: form.ospf.router_id.trim(),
      interfaces: form.ospf.interfaces.map((o) => ({ interface: o.interface.trim(), area: num(o.area) ?? 0 })),
      passive_interfaces: parsePorts(form.ospf.passive),
    }
  }
  if (form.eigrp.on) {
    routing.eigrp = {
      asn: num(form.eigrp.asn),
      router_id: form.eigrp.router_id.trim(),
      networks: split(form.eigrp.networks),
      passive_interfaces: parsePorts(form.eigrp.passive),
    }
  }
  if (form.bgp.on) {
    routing.bgp = {
      asn: num(form.bgp.asn),
      router_id: form.bgp.router_id.trim(),
      neighbors: form.bgp.neighbors.map((n) => ({ ip: n.ip.trim(), remote_as: num(n.remote_as), description: text(n.description) })),
      networks: split(form.bgp.networks),
    }
  }
  if (Object.keys(routing).length) plan.routing = routing
  plan.custom_commands = String(form.custom || '')
    .split('\n')
    .map((s) => s.trimEnd())
    .filter((s) => s.trim())
  return plan
}

/** Server errors use plan paths ("vlans.0.id"); schema errors start with "plan.". */
export function normalizeErrors(fields) {
  const out = {}
  for (const [k, v] of Object.entries(fields || {})) out[k.replace(/^plan\./, '')] = v
  return out
}

/** First error at `path` or below it ("access.0" also finds "access.0.interfaces.3"). */
export function errorAt(errors, path) {
  if (!errors) return undefined
  if (errors[path]) return errors[path]
  const key = Object.keys(errors).find((k) => k.startsWith(`${path}.`))
  return key ? errors[key] : undefined
}

// Map a field path to the requirement section that shows it (for the "fix it" links).
const SECTION_OF = {
  basic: 'basic', ssh: 'ssh', hardening: 'hardening', vlans: 'vlans', access: 'access', trunks: 'trunks',
  svis: 'svis', interfaces: 'interfaces', dhcp: 'dhcp', nat: 'nat', statics: 'statics', custom_commands: 'custom',
  default_gateway: 'gateway',
  commands: 'custom', revert_minutes: 'options', save: 'options',
}
export function sectionOf(path) {
  const [head, second] = path.split('.')
  if (head === 'routing') return second || 'ospf'
  return SECTION_OF[head] || 'options'
}

const str = (v) => (v === null || v === undefined ? '' : String(v))
const joined = (list) => (list || []).join(', ')

/** ConfigPlan → wizard form (for saved templates). The inverse of toPlan; unknown fields are ignored. */
export function fromPlan(plan = {}) {
  const f = emptyForm()
  if (plan.basic) f.basic = { on: true, hostname: str(plan.basic.hostname), domain: str(plan.basic.domain) }
  if (plan.ssh) {
    const s = plan.ssh
    f.ssh = { on: true, username: str(s.username), rsa_modulus: str(s.rsa_modulus ?? 2048), vty_timeout_minutes: str(s.vty_timeout_minutes ?? 10), set_enable_secret: Boolean(s.set_enable_secret), regenerate_keys: Boolean(s.regenerate_keys) }
  }
  if (plan.hardening) {
    const h = plan.hardening
    f.hardening = { on: true, password_encryption: h.password_encryption !== false, disable_http: h.disable_http !== false, login_block: Boolean(h.login_block), banner: str(h.banner) }
  }
  f.vlans = (plan.vlans || []).map((v) => ({ id: str(v.id), name: str(v.name) }))
  f.access = (plan.access || []).map((a) => ({
    interfaces: joined(a.interfaces), vlan: str(a.vlan), description: str(a.description), portfast: a.portfast !== false,
    port_security: Boolean(a.port_security), ps_max: str(a.port_security?.maximum ?? 1), ps_violation: a.port_security?.violation || 'shutdown', ps_sticky: Boolean(a.port_security?.sticky),
  }))
  f.trunks = (plan.trunks || []).map((t) => ({ interface: str(t.interface), allowed: joined(t.allowed_vlans), native: str(t.native_vlan ?? 1), description: str(t.description) }))
  f.svis = (plan.svis || []).map((s) => ({ vlan: str(s.vlan), ip: str(s.ip), description: str(s.description) }))
  f.interfaces = (plan.interfaces || []).map((i) => ({ interface: str(i.interface), ip: str(i.ip), description: str(i.description) }))
  f.dhcp = (plan.dhcp || []).map((d) => ({
    name: str(d.name), network: str(d.network), default_router: str(d.default_router), dns: joined(d.dns_servers), domain: str(d.domain), lease_days: str(d.lease_days ?? 1),
    excluded: (d.excluded || []).map((r) => (r.end ? `${r.start}-${r.end}` : r.start)).join(', '),
  }))
  if (plan.nat) f.nat = { on: true, inside: joined(plan.nat.inside_interfaces), outside: str(plan.nat.outside_interface), networks: joined(plan.nat.inside_networks) }
  f.statics = (plan.statics || []).map((s) => ({ prefix: str(s.prefix), target: str(s.next_hop || s.interface), distance: str(s.distance) }))
  f.default_gateway = str(plan.default_gateway)
  const r = plan.routing || {}
  if (r.ospf) f.ospf = { on: true, process_id: str(r.ospf.process_id ?? 1), router_id: str(r.ospf.router_id), interfaces: (r.ospf.interfaces || []).map((o) => ({ interface: str(o.interface), area: str(o.area ?? 0) })), passive: joined(r.ospf.passive_interfaces) }
  if (r.eigrp) f.eigrp = { on: true, asn: str(r.eigrp.asn), router_id: str(r.eigrp.router_id), networks: joined(r.eigrp.networks), passive: joined(r.eigrp.passive_interfaces) }
  if (r.bgp) f.bgp = { on: true, asn: str(r.bgp.asn), router_id: str(r.bgp.router_id), neighbors: (r.bgp.neighbors || []).map((n) => ({ ip: str(n.ip), remote_as: str(n.remote_as), description: str(n.description) })), networks: joined(r.bgp.networks) }
  f.custom = (plan.custom_commands || []).join('\n')
  f.save = plan.save !== false
  f.revert_minutes = str(plan.revert_minutes ?? 10)
  return f
}
