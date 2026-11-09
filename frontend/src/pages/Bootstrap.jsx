import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Eye, PlugZap } from 'lucide-react'
import { ConfigureTabs, CreateJob, FinishedJob, JobPreview, SelectInput, TextInput, useJobWizard } from '../components/Wizard.jsx'
import { Alert, Empty, ErrorNote, PageHeader, Panel, SkeletonRows } from '../components/ui.jsx'
import { categoryLabel } from '../lib/labels.js'
import { bootstrapBody, emptyBootstrap } from '../lib/wizards.js'

const CONSOLE = ['serial', 'telnet_lab']

function consoleLabel(d) {
  const c = d.connection || {}
  return c.method === 'serial' ? `serial ${c.serial_port} @ ${c.baud}` : `lab console ${d.mgmt_ip}:${c.port}`
}

export default function Bootstrap() {
  const [form, setForm] = useState(emptyBootstrap)
  const { devices, loadError, preview, setPreview, previewError, loading, runPreview, job, setJob, onCreated, reset } = useJobWizard()

  const consoles = useMemo(() => (devices || []).filter((d) => CONSOLE.includes(d.connection?.method)), [devices])
  const device = consoles.find((d) => d.id === form.device_id)
  const category = device?.category
  const errors = preview?.errors || {}
  const e = (k) => errors[`bootstrap.${k}`]

  const set = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }))
    setPreview(null)
  }

  function startOver() {
    reset()
    setForm(emptyBootstrap())
  }

  return (
    <>
      <PageHeader title="First-time setup" subtitle="A new device over its console: hostname, management address, admin user and SSH – then an SSH test login." />
      <div className="stack">
        <ConfigureTabs />
        {job ? (
          <FinishedJob job={job} setJob={setJob} again="Set up another device" onAgain={startOver} />
        ) : (
          <>
            <Panel title="How it works">
              <ol className="stack" style={{ margin: 0, paddingLeft: 'var(--space-5)' }}>
                <li>Connect the console: a USB console cable (the device's connection is <em>Serial</em>, for example COM3), or the GNS3 / CML console port of an emulator (<em>Lab console</em>, Telnet to 127.0.0.1 or a private address).</li>
                <li>NetConfig Studio answers <code>no</code> to the "initial configuration dialog" and applies the settings below inside the automatic-rollback timer.</li>
                <li>After saving, it tries an SSH login to the new address with the new admin user. Only if that works is the device switched to SSH; otherwise it stays on the console.</li>
              </ol>
            </Panel>
            <Panel title="Device and settings">
              <ErrorNote error={loadError} />
              {!devices && !loadError && <SkeletonRows rows={3} />}
              {devices && consoles.length === 0 && (
                <Empty icon={PlugZap} title="No device on a console" action={<Link className="btn primary" to="/devices">Add a device</Link>}>
                  Add the new device to the inventory with the connection method Serial console or Lab console.
                </Empty>
              )}
              {consoles.length > 0 && (
                <div className="stack">
                  <SelectInput label="Device" value={form.device_id} onChange={(v) => set('device_id', v)} error={errors.device_id}
                    options={[['', 'Choose a device…'], ...consoles.map((d) => [d.id, `${d.name} · ${categoryLabel(d.category)} · ${consoleLabel(d)}`])]} />
                  {device?.connection?.method === 'telnet_lab' && (
                    <Alert tone="warning" title="Insecure lab console.">Telnet is clear text. Use it only for emulators or an isolated lab.</Alert>
                  )}
                  <div className="form-grid">
                    <TextInput label="Hostname" value={form.hostname} onChange={(v) => set('hostname', v)} error={e('hostname')} maxLength={63} />
                    <TextInput label="Domain name" value={form.domain} onChange={(v) => set('domain', v)} error={e('domain')} placeholder="lab.example.net" hint="Needed for the RSA keys" maxLength={253} />
                    <TextInput label="Admin username" value={form.admin_username} onChange={(v) => set('admin_username', v)} error={e('admin_username')} hint="Its password is asked for when the job runs" maxLength={32} />
                    {category === 'router' ? (
                      <TextInput label="Management interface" value={form.interface} onChange={(v) => set('interface', v)} error={e('mgmt.interface')} mono placeholder="GigabitEthernet0/0" />
                    ) : (
                      <TextInput label="Management VLAN" value={form.vlan} onChange={(v) => set('vlan', v)} error={e('mgmt.vlan')} inputMode="numeric" hint="The switch's address lives on this VLAN interface" />
                    )}
                    <TextInput label="Management address/prefix" value={form.ip} onChange={(v) => set('ip', v)} error={e('mgmt.ip')} mono placeholder="10.0.0.2/24" />
                    <TextInput label="Default gateway" value={form.gateway} onChange={(v) => set('gateway', v)} error={e('mgmt.gateway')} mono placeholder="10.0.0.1"
                      hint={category === 'router' ? 'Added as a default route' : 'ip default-gateway'} />
                    <SelectInput label="RSA key size" value={form.rsa_modulus} onChange={(v) => set('rsa_modulus', v)} options={[['2048', '2048 bits'], ['3072', '3072 bits'], ['4096', '4096 bits']]} error={e('rsa_modulus')} />
                    <TextInput label="SSH idle timeout (minutes)" value={form.vty_timeout_minutes} onChange={(v) => set('vty_timeout_minutes', v)} error={e('vty_timeout_minutes')} inputMode="numeric" />
                    <TextInput label="Rollback timer (minutes)" value={form.revert_minutes} onChange={(v) => set('revert_minutes', v)} error={e('revert_minutes')} inputMode="numeric" />
                  </div>
                  <label className="checkbox">
                    <input type="checkbox" checked={form.hardening} onChange={(ev) => set('hardening', ev.target.checked)} />
                    <span>Basic hardening (password encryption, no web server, login blocking)</span>
                  </label>
                  <div className="form-actions">
                    <button type="button" className="btn primary" disabled={loading || !form.device_id} onClick={() => runPreview(bootstrapBody(form, category))}>
                      <Eye size={18} aria-hidden="true" /> {loading ? 'Checking…' : 'Preview commands'}
                    </button>
                  </div>
                </div>
              )}
            </Panel>
            <ErrorNote error={previewError} />
            <JobPreview preview={preview} />
            {preview?.ok && (
              <CreateJob body={bootstrapBody(form, category)} production={preview.production} what="this setup" onCreated={onCreated} />
            )}
          </>
        )}
      </div>
    </>
  )
}
