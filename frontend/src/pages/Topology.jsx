// Full-size network map: how the devices are connected, which port goes to which, and the status of each device.
// Same live data as Overview (GET /api/overview). Links come from LLDP/CDP neighbour tables (read device facts) and
// from the uplink port set on access points and cameras.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Network, RefreshCw, Search, Server, Waypoints } from 'lucide-react'
import { useAuth } from '../lib/auth.jsx'
import { reveal, stacked } from '../lib/scroll.js'
import { useOverview } from '../lib/useOverview.js'
import DevicePanel from '../components/DevicePanel.jsx'
import TopologyMap from '../components/TopologyMap.jsx'
import { Alert, Empty, ErrorNote, PageHeader, Panel, Skeleton, formatDate } from '../components/ui.jsx'

const FILTERS = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'up', label: 'Up', test: (n) => n.reachable === true },
  { id: 'down', label: 'Down', test: (n) => n.reachable === false },
  { id: 'unknown', label: 'Not checked', test: (n) => n.reachable == null },
]
const FOUND_BY = { lldp: 'LLDP', cdp: 'CDP', uplink: 'Uplink (set in Devices)' }

function Legend() {
  return (
    <div className="legend map-legend" aria-label="Legend">
      <span><i className="dot up" aria-hidden="true" />Up</span>
      <span><i className="dot down" aria-hidden="true" />Down</span>
      <span><i className="dot unknown" aria-hidden="true" />Not checked</span>
      <span><i className="line" aria-hidden="true" />LLDP / CDP link</span>
      <span><i className="line uplink" aria-hidden="true" />Uplink</span>
      <span><i className="line down" aria-hidden="true" />Link to a device that is down</span>
    </div>
  )
}

export default function Topology() {
  const { can } = useAuth()
  const { data, error, load, checking, notice, refresh } = useOverview()
  const [selected, setSelected] = useState(null)
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

  const nodes = useMemo(() => data?.topology.nodes || [], [data])
  const inventory = nodes.filter((n) => !n.external)
  const names = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.name])), [nodes])

  // Status filters apply to inventory devices; neighbours outside the inventory are only shown under "All".
  const shown = useMemo(() => {
    const test = FILTERS.find((f) => f.id === filter).test
    const term = q.trim().toLowerCase()
    return nodes.filter((n) => (n.external ? filter === 'all' : test(n))
      && (!term || n.name.toLowerCase().includes(term) || (n.model_name || '').toLowerCase().includes(term)))
  }, [nodes, filter, q])
  const shownIds = useMemo(() => new Set(shown.map((n) => n.id)), [shown])
  const links = useMemo(() => (data?.topology.links || []).filter((l) => shownIds.has(l.a) && shownIds.has(l.b)),
    [data, shownIds])
  const counts = Object.fromEntries(FILTERS.map((f) => [f.id, inventory.filter(f.test).length]))

  // On a phone the device panel sits below the map: bring it into view when a device is picked.
  function select(id) {
    setSelected(id)
    if (stacked()) requestAnimationFrame(() => reveal(document.getElementById('device-panel')))
  }

  const deviceButton = (id) => (names[id] && !String(id).startsWith('ext:')
    ? <button type="button" className="link-button" onClick={() => select(id)}>{names[id]}</button>
    : <span>{names[id] || id}</span>)

  return (
    <>
      <PageHeader title="Topology" subtitle={data?.last_poll ? `Status checked ${formatDate(data.last_poll)}` : 'How your devices are connected'}>
        {can('engineer') && (
          <button type="button" className="btn" onClick={refresh} disabled={checking} aria-busy={checking}>
            <RefreshCw size={16} aria-hidden="true" className={checking ? 'spin' : undefined} /> {checking ? 'Checking…' : 'Check status now'}
          </button>
        )}
      </PageHeader>
      {notice && <Alert tone="info">{notice}</Alert>}
      <ErrorNote error={error} />

      <Panel title="Network map" subtitle="Select a device to see its details. Arrow keys move between devices.">
        {!data ? <Skeleton height={360} /> : inventory.length === 0 ? (
          <Empty icon={Network} title="No devices yet" action={<Link className="btn primary" to="/devices">Add a device</Link>}>
            Add your switches and routers, then read their facts to draw the map.
          </Empty>
        ) : (
          <div className="stack">
            <div className="map-tools">
              <div className="segmented" role="group" aria-label="Show devices">
                {FILTERS.map((f) => (
                  <button type="button" key={f.id} className="subnav-link" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                    {f.label} ({counts[f.id]})
                  </button>
                ))}
              </div>
              <div className="search">
                <Search size={16} aria-hidden="true" />
                <label className="sr-only" htmlFor="map-search">Search devices by name or model</label>
                <input id="map-search" className="input" placeholder="Search devices" value={q} maxLength={64}
                  onChange={(e) => setQ(e.target.value)} />
              </div>
            </div>
            <Legend />
            {shown.length === 0 ? (
              <Empty icon={Search} title="No device matches">Change the filter or the search.</Empty>
            ) : (
              <TopologyMap nodes={shown} links={links} selectedId={selected} onSelect={select} />
            )}
          </div>
        )}
      </Panel>

      <div className="grid two">
        <Panel title="Connections" subtitle="Which port is connected to which">
          {!data ? <Skeleton height={160} /> : links.length === 0 ? (
            <Empty icon={Waypoints} title="No connections found yet">
              Select a device on the map and choose <strong>Read device facts</strong> to find its LLDP/CDP neighbours,
              or set the uplink switch port of an access point or camera under Devices.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Connections between devices</caption>
                <thead>
                  <tr><th scope="col">Device</th><th scope="col">Port</th><th scope="col">Connected to</th><th scope="col">Port</th><th scope="col">Found by</th></tr>
                </thead>
                <tbody>
                  {links.map((l, i) => (
                    <tr key={i}>
                      <td>{deviceButton(l.a)}</td>
                      <td className="mono">{l.a_port || '—'}</td>
                      <td>{deviceButton(l.b)}</td>
                      <td className="mono">{l.b_port || '—'}</td>
                      <td>{FOUND_BY[l.source] || l.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Device" id="device-panel">
          {selected ? <DevicePanel id={selected} onChanged={load} /> : (
            <Empty icon={Server} title="No device selected">Select a device on the map or in the connections table.</Empty>
          )}
        </Panel>
      </div>
    </>
  )
}
