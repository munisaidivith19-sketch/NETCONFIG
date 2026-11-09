import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cable, Eye } from 'lucide-react'
import { ConfigureTabs, CreateJob, FinishedJob, JobPreview, useJobWizard } from '../components/Wizard.jsx'
import { Alert, Empty, ErrorNote, PageHeader, Panel, SelectInput, SkeletonRows, TextInput } from '../components/ui.jsx'
import { setPath } from '../lib/plan.js'
import { emptyLink, linkAddresses, linkBody } from '../lib/wizards.js'

const PROTOCOLS = [['ospf', 'OSPF'], ['eigrp', 'EIGRP'], ['bgp', 'eBGP'], ['none', 'Addresses only']]
const ROUTING = ['router', 'l3switch']

function Side({ side, label, form, set, routers, other, errors }) {
  const e = (k) => errors[`link.${side}.${k}`]
  const end = form[side]
  const device = routers.find((d) => d.id === end.device_id)
  const options = [['', 'Choose a device…'], ...routers.filter((d) => d.id !== other).map((d) => [d.id, `${d.name} · ${d.model_name || d.model_id}`])]
  return (
    <fieldset className="section-card stack">
      <legend><strong>{label}</strong></legend>
      <SelectInput label="Device" value={end.device_id} onChange={(v) => set(`${side}.device_id`, v)} options={options} error={e('device_id')} />
      <div className="form-grid">
        <TextInput maxLength={80} label="Interface" value={end.interface} onChange={(v) => set(`${side}.interface`, v)} error={e('interface')} mono
          placeholder="GigabitEthernet0/1" hint={device?.production ? 'Production device: needs approval.' : 'Short names such as Gi0/1 work too.'} />
        {form.protocol !== 'none' && (
          <TextInput maxLength={80} label="Router ID" value={end.router_id} onChange={(v) => set(`${side}.router_id`, v)} error={e('router_id')} mono placeholder={side === 'a' ? '1.1.1.1' : '2.2.2.2'} />
        )}
        {form.protocol === 'bgp' && (
          <TextInput maxLength={80} label="Local AS" value={end.asn} onChange={(v) => set(`${side}.asn`, v)} error={e('asn')} inputMode="numeric" placeholder={side === 'a' ? '65001' : '65002'} />
        )}
      </div>
    </fieldset>
  )
}

export default function RouterLink() {
  const [form, setForm] = useState(emptyLink)
  const { devices, loadError, preview, setPreview, previewError, loading, runPreview, job, setJob, onCreated, reset } = useJobWizard()

  const routers = useMemo(() => (devices || []).filter((d) => ROUTING.includes(d.category) && d.connection?.method !== 'none'), [devices])
  const addresses = linkAddresses(form.subnet)
  const errors = preview?.errors || {}

  const set = (path, value) => {
    setForm((f) => setPath(f, path, value))
    setPreview(null)
  }

  return (
    <>
      <PageHeader title="Router link" subtitle="Both ends of a point-to-point link: addresses and routing on each side, checked to match, applied as one job." />
      <div className="stack">
        <ConfigureTabs />
        {job ? (
          <FinishedJob job={job} setJob={setJob} again="Configure another link" onAgain={reset} />
        ) : (
          <>
            <Panel title="The link" subtitle="Pick two routers (or Layer 3 switches) and the ports that face each other.">
              <ErrorNote error={loadError} />
              {!devices && !loadError && <SkeletonRows rows={3} />}
              {devices && routers.length < 2 && (
                <Empty icon={Cable} title="Two routers needed" action={<Link className="btn primary" to="/devices">Add devices</Link>}>
                  Add at least two routers or Layer 3 switches with a connection method to the inventory.
                </Empty>
              )}
              {routers.length >= 2 && (
                <div className="stack">
                  <div className="form-grid">
                    <TextInput maxLength={80} label="Link subnet" value={form.subnet} onChange={(v) => set('subnet', v)} error={errors['link.subnet']} mono placeholder="10.255.0.0/30"
                      hint={addresses ? `A gets ${addresses[0]}, B gets ${addresses[1]}` : 'A /30 or /31 network'} />
                    <SelectInput label="Routing protocol" value={form.protocol} onChange={(v) => set('protocol', v)} options={PROTOCOLS} error={errors['link.protocol']} />
                    {form.protocol === 'ospf' && (
                      <>
                        <TextInput maxLength={80} label="OSPF process ID" value={form.ospf_process_id} onChange={(v) => set('ospf_process_id', v)} error={errors['link.ospf_process_id']} inputMode="numeric" />
                        <TextInput maxLength={80} label="OSPF area" value={form.ospf_area} onChange={(v) => set('ospf_area', v)} error={errors['link.ospf_area']} inputMode="numeric" hint="The same on both sides" />
                      </>
                    )}
                    {form.protocol === 'eigrp' && (
                      <TextInput maxLength={80} label="EIGRP AS" value={form.eigrp_asn} onChange={(v) => set('eigrp_asn', v)} error={errors['link.eigrp_asn']} inputMode="numeric" hint="The same on both sides" />
                    )}
                    <TextInput maxLength={80} label="Description (optional)" value={form.description} onChange={(v) => set('description', v)} error={errors['link.description']} hint='Default: "link to <other router>"' />
                    <TextInput maxLength={80} label="Rollback timer (minutes)" value={form.revert_minutes} onChange={(v) => set('revert_minutes', v)} error={errors['link.revert_minutes']} inputMode="numeric" hint="5–120; both sides share this window" />
                  </div>
                  <div className="grid two">
                    <Side side="a" label="Side A" form={form} set={set} routers={routers} other={form.b.device_id} errors={errors} />
                    <Side side="b" label="Side B" form={form} set={set} routers={routers} other={form.a.device_id} errors={errors} />
                  </div>
                  {errors.link && <Alert tone="danger">{errors.link}</Alert>}
                  <div className="form-actions">
                    <button type="button" className="btn primary" disabled={loading} onClick={() => runPreview(linkBody(form))}>
                      <Eye size={18} aria-hidden="true" /> {loading ? 'Checking…' : 'Preview both sides'}
                    </button>
                  </div>
                </div>
              )}
            </Panel>
            <ErrorNote error={previewError} />
            <JobPreview preview={preview} />
            {preview?.ok && (
              <CreateJob body={linkBody(form)} production={preview.production} what="this link" onCreated={onCreated} />
            )}
          </>
        )}
      </div>
    </>
  )
}
