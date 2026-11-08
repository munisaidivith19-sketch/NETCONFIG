// Human-readable labels shared by several pages.
import { Camera, Network, Radio, Router, Server, ToggleRight } from 'lucide-react'

export const CATEGORIES = [
  { id: 'switch', label: 'Switch', icon: ToggleRight, hint: 'Layer 2 access switch' },
  { id: 'l3switch', label: 'Layer 3 switch', icon: Network, hint: 'Switching + routing (SVIs)' },
  { id: 'router', label: 'Router', icon: Router, hint: 'WAN, NAT, routing protocols' },
  { id: 'ap', label: 'Access point', icon: Radio, hint: 'Managed by its controller' },
  { id: 'camera', label: 'Camera', icon: Camera, hint: 'Read-only information' },
  { id: 'unmanaged', label: 'Unmanaged', icon: Server, hint: 'Inventory only' },
]
export const categoryLabel = (id) => CATEGORIES.find((c) => c.id === id)?.label || id || '—'
export const categoryIcon = (id) => CATEGORIES.find((c) => c.id === id)?.icon || Server

export const CAPABILITIES = [
  ['vlans', 'VLANs'],
  ['access', 'Access ports'],
  ['trunk', 'Trunks'],
  ['svi', 'SVIs'],
  ['routed_if', 'Routed ports'],
  ['dhcp', 'DHCP server'],
  ['nat', 'NAT'],
  ['static', 'Static routes'],
  ['ospf', 'OSPF'],
  ['eigrp', 'EIGRP'],
  ['bgp', 'BGP'],
  ['ssh', 'SSH setup'],
]

export const SUPPORT = {
  tested: { tone: 'success', label: 'Tested in lab' },
  experimental: { tone: 'warning', label: 'Experimental' },
  planned: { tone: 'info', label: 'Planned' },
  inventory: { tone: '', label: 'Inventory only' },
}

export const CONNECTIONS = {
  ssh: 'SSH',
  serial: 'Serial console',
  telnet_lab: 'Lab console (telnet, insecure)',
  none: 'Not configurable',
}
