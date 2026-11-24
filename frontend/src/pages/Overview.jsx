import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, ClipboardCheck, History, Network, RefreshCw, Server, Waypoints } from 'lucide-react'
import { useAuth } from '../lib/auth.jsx'
import { categoryLabel } from '../lib/labels.js'
import { STATUS } from '../lib/jobs.js'
import { reveal, stacked } from '../lib/scroll.js'
import { useOverview } from '../lib/useOverview.js'
import DevicePanel from '../components/DevicePanel.jsx'
import TopologyMap from '../components/TopologyMap.jsx'
import { BarList, StackedColumns, TableToggle, TrendLine } from '../components/charts.jsx'
import { Alert, Badge, Empty, ErrorNote, PageHeader, Panel, Skeleton, SkeletonRows, formatDate } from '../components/ui.jsx'

const OUTCOMES = [
  { key: 'success', label: 'Succeeded', color: 'var(--chart-good)' },
  { key: 'failed', label: 'Failed or rolled back', color: 'var(--chart-bad)' },
]

function Kpi({ icon: Icon, label, value, note }) {
  return (
    <div className="glass kpi">
      <span className="kpi-label"><span className="kpi-icon"><Icon size={16} aria-hidden="true" /></span>{label}</span>
      <span className="kpi-value">{value}</span>
      {note && <span className="kpi-note">{note}</span>}
    </div>
  )
}

function KpiSkeleton() {
  return (
    <div className="grid kpis" aria-busy="true" aria-label="Loading">
      {[0, 1, 2, 3].map((i) => <div key={i} className="glass kpi"><Skeleton width="60%" /><Skeleton height={30} width="40%" /></div>)}
    </div>
  )
}

export default function Overview() {
  const { can } = useAuth()
  const { data, error, load, checking, notice, refresh } = useOverview()
  const [selected, setSelected] = useState(null)

  // On a phone the device panel sits below the map: bring it into view when a device is picked.
  function select(id) {
    setSelected(id)
    if (stacked()) requestAnimationFrame(() => reveal(document.getElementById('device-panel')))
  }

  const k = data?.kpis
  const nodes = data?.topology.nodes || []
  const realNodes = nodes.filter((n) => !n.external)

  return (
    <>
      <PageHeader title="Overview" subtitle={data?.last_poll ? `Status checked ${formatDate(data.last_poll)}` : 'Live status of your network'}>
        {can('engineer') && (
          <button type="button" className="btn" onClick={refresh} disabled={checking} aria-busy={checking}>
            <RefreshCw size={16} aria-hidden="true" className={checking ? 'spin' : undefined} /> {checking ? 'Checking…' : 'Check status now'}
          </button>
        )}
      </PageHeader>
      {notice && <Alert tone="info">{notice}</Alert>}
      <ErrorNote error={error} />

      {!data ? <KpiSkeleton /> : (
        <div className="grid kpis">
          <Kpi icon={Server} label="Devices reachable" value={`${k.up} / ${k.devices}`}
            note={k.devices ? `${k.down} down · ${k.unknown} not checked` : 'No devices yet'} />
          <Kpi icon={Activity} label="Jobs in the last 7 days" value={k.jobs_7d}
            note={k.success_rate_7d == null ? 'None finished yet' : `${k.success_rate_7d}% succeeded · ${k.failed_7d} failed or rolled back`} />
          <Kpi icon={ClipboardCheck} label="Waiting" value={k.waiting}
            note={k.running ? `${k.running} running now` : 'For approval or to be run'} />
          <Kpi icon={AlertTriangle} label="Model warnings" value={k.model_mismatches}
            note={k.model_mismatches ? 'Device reports a different model or OS' : 'Read device facts to check'} />
        </div>
      )}

      <div className="grid two">
        <Panel title="Network map" subtitle="Links come from LLDP/CDP (read device facts) and access point uplinks."
          actions={<Link className="btn ghost small" to="/topology"><Waypoints size={14} aria-hidden="true" /> Full map</Link>}>
          {!data ? <Skeleton height={260} /> : realNodes.length === 0 ? (
            <Empty icon={Network} title="No devices yet" action={<Link className="btn primary" to="/devices">Add a device</Link>}>
              Add your switches and routers, then read their facts to draw the map.
            </Empty>
          ) : (
            <div className="stack">
              <TopologyMap nodes={nodes} links={data.topology.links} selectedId={selected} onSelect={select} />
              {data.topology.links.length === 0 && (
                <p className="faint">No links yet: select a device and choose <strong>Read device facts</strong> to find its neighbours.</p>
              )}
            </div>
          )}
        </Panel>
        <Panel title="Device" id="device-panel">
          {selected ? <DevicePanel id={selected} onChanged={load} /> : (
            <Empty icon={Server} title="No device selected">Select a device on the map to see its status, facts and VLANs.</Empty>
          )}
        </Panel>
      </div>

      <div className="grid halves">
        <Panel title="Jobs per day" subtitle="Last 14 days, by result">
          {!data ? <Skeleton height={180} /> : (
            <>
              <StackedColumns data={data.jobs_by_day} series={OUTCOMES} extra={[{ key: 'other', label: 'Other (waiting, cancelled, expired)' }]}
                label="Jobs per day over the last 14 days, succeeded and failed" />
              <TableToggle caption="Jobs per day" columns={['Day', 'Succeeded', 'Failed or rolled back', 'Other']}
                rows={data.jobs_by_day.map((d) => [d.date, d.success, d.failed, d.other])} />
            </>
          )}
        </Panel>
        <Panel title="Reachable devices" subtitle="Last 24 hours">
          {!data ? <Skeleton height={160} /> : data.status_history.length === 0 ? (
            <Empty icon={Activity} title="No status checks yet">Device status is checked every minute while NetConfig Studio runs. The first results appear shortly after you add a device.</Empty>
          ) : (
            <>
              <TrendLine points={data.status_history.map((s) => ({ at: s.at, value: s.up }))} max={k.devices}
                label="Reachable devices over the last 24 hours" valueLabel="devices reachable" />
              <TableToggle caption="Reachable devices" columns={['Time', 'Reachable', 'Down', 'Not checked']}
                rows={data.status_history.map((s) => [formatDate(s.at), s.up, s.down, s.unknown])} />
            </>
          )}
        </Panel>
      </div>

      <div className="grid halves">
        <Panel title="Devices by category">
          {!data ? <SkeletonRows rows={3} /> : Object.keys(data.devices_by_category).length === 0 ? <p className="faint">No devices yet.</p> : (
            <BarList label="Devices by category" items={Object.entries(data.devices_by_category)
              .sort((a, b) => b[1] - a[1]).map(([c, n]) => ({ label: categoryLabel(c), value: n }))} />
          )}
        </Panel>
        <Panel title="Recent jobs" actions={<Link className="btn ghost small" to="/history"><History size={14} aria-hidden="true" /> History</Link>}>
          {!data ? <SkeletonRows rows={3} /> : data.recent_jobs.length === 0 ? (
            <Empty icon={History} title="No jobs yet">A job is created when you push a change from Configure.</Empty>
          ) : (
            <ul className="recent-list">
              {data.recent_jobs.map((j) => (
                <li key={j.id}>
                  <Link to={`/history/${j.id}`}>{j.devices.join(', ') || 'Job'}</Link>
                  <Badge tone={STATUS[j.status]?.tone || j.status}>{STATUS[j.status]?.label || j.status}</Badge>
                  <span className="faint">{formatDate(j.created_at)} · {j.requested_by}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  )
}
