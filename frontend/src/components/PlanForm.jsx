import { Plus, Trash2 } from 'lucide-react'
import { NEW_ROWS, errorAt } from '../lib/plan.js'
import { Alert, Field } from './ui.jsx'

// Requirements step of the Configure wizard. Sections appear only when the target model supports them
// (capabilities from the backend). Errors come from the backend, keyed by plan path.

function Input({ label, value, onChange, error, hint, placeholder, type = 'text', mono = false, inputMode, maxLength }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(props) => (
        <input
          {...props}
          className="input"
          style={mono ? { fontFamily: 'var(--font-mono)' } : undefined}
          type={type}
          value={value}
          placeholder={placeholder}
          inputMode={inputMode}
          maxLength={maxLength}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Field>
  )
}

function Check({ label, checked, onChange, disabled }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function Select({ label, value, onChange, options, error }) {
  return (
    <Field label={label} error={error}>
      {(props) => (
        <select {...props} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

function Section({ id, title, hint, on, onToggle, error, children }) {
  return (
    <section className="section-card" id={`sec-${id}`} aria-labelledby={`sec-${id}-title`}>
      <div className="row between">
        <div>
          <h3 id={`sec-${id}-title`} style={{ margin: 0 }}>
            {title}
          </h3>
          {hint && <p className="faint" style={{ margin: 0 }}>{hint}</p>}
        </div>
        {onToggle && <Check label={on ? 'Included' : 'Include'} checked={on} onChange={onToggle} />}
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {(on ?? true) && <div className="stack" style={{ marginTop: 'var(--space-3)' }}>{children}</div>}
    </section>
  )
}

function Rows({ items, onAdd, onRemove, addLabel, render, max }) {
  return (
    <>
      {items.map((item, i) => (
        <div className="list-row" key={i}>
          {render(item, i)}
          <button type="button" className="btn ghost icon" aria-label={`Remove row ${i + 1}`} onClick={() => onRemove(i)}>
            <Trash2 size={18} aria-hidden="true" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn small" onClick={onAdd} disabled={max !== undefined && items.length >= max}>
          <Plus size={16} aria-hidden="true" /> {addLabel}
        </button>
      </div>
    </>
  )
}

export default function PlanForm({ form, setForm, caps, errors, production, portHint }) {
  const has = (c) => caps.has(c)
  const set = (path, value) =>
    setForm((f) => {
      const next = structuredClone(f)
      const keys = path.split('.')
      let o = next
      for (const k of keys.slice(0, -1)) o = o[k]
      o[keys.at(-1)] = value
      return next
    })
  const add = (list, row) => setForm((f) => ({ ...f, [list]: [...f[list], row()] }))
  const remove = (list, i) => setForm((f) => ({ ...f, [list]: f[list].filter((_, j) => j !== i) }))
  const e = (path) => errorAt(errors, path)
  const exact = (path) => errors?.[path]

  return (
    <div className="stack">
      <Section id="basic" title="Basic settings" hint="Hostname and domain name." on={form.basic.on} onToggle={(v) => set('basic.on', v)} error={exact('basic')}>
        <div className="form-grid">
          <Input label="Hostname" value={form.basic.hostname} onChange={(v) => set('basic.hostname', v)} error={e('basic.hostname')} hint="Letters, digits and hyphens" maxLength={63} />
          <Input label="Domain name" value={form.basic.domain} onChange={(v) => set('basic.domain', v)} error={e('basic.domain')} placeholder="lab.example.net" maxLength={253} />
        </div>
      </Section>

      {has('ssh') && (
        <Section id="ssh" title="SSH v2 and local admin user" hint="Needs the hostname and domain name above. The user's password is asked for when the job runs." on={form.ssh.on} onToggle={(v) => set('ssh.on', v)} error={exact('ssh')}>
          <div className="form-grid">
            <Input label="Local username" value={form.ssh.username} onChange={(v) => set('ssh.username', v)} error={e('ssh.username')} maxLength={32} />
            <Select label="RSA key size" value={form.ssh.rsa_modulus} onChange={(v) => set('ssh.rsa_modulus', v)} options={[['2048', '2048 bits'], ['3072', '3072 bits'], ['4096', '4096 bits']]} error={e('ssh.rsa_modulus')} />
            <Input label="Idle timeout (minutes)" value={form.ssh.vty_timeout_minutes} onChange={(v) => set('ssh.vty_timeout_minutes', v)} error={e('ssh.vty_timeout_minutes')} inputMode="numeric" />
          </div>
          <div className="row">
            <Check label="Also set the enable secret" checked={form.ssh.set_enable_secret} onChange={(v) => set('ssh.set_enable_secret', v)} />
            <Check label="Replace existing RSA keys" checked={form.ssh.regenerate_keys} onChange={(v) => set('ssh.regenerate_keys', v)} />
          </div>
        </Section>
      )}

      <Section id="hardening" title="Hardening" hint="Turn off the web server, slow down password guessing, add a login banner." on={form.hardening.on} onToggle={(v) => set('hardening.on', v)} error={exact('hardening')}>
        <div className="row">
          <Check label="service password-encryption" checked={form.hardening.password_encryption} onChange={(v) => set('hardening.password_encryption', v)} />
          <Check label="Disable HTTP/HTTPS server" checked={form.hardening.disable_http} onChange={(v) => set('hardening.disable_http', v)} />
          <Check label="Block logins after 5 failures (120 s)" checked={form.hardening.login_block} onChange={(v) => set('hardening.login_block', v)} />
        </div>
        <Input label="Login banner" value={form.hardening.banner} onChange={(v) => set('hardening.banner', v)} error={e('hardening.banner')} hint="One line. Letters, digits, spaces and . , : / ( ) @ + = ! ? ' -" maxLength={240} />
      </Section>

      {has('vlans') && (
        <Section id="vlans" title="VLANs" hint="IDs 2–4094 (1002–1005 are reserved)." error={exact('vlans')}>
          <Rows items={form.vlans} addLabel="Add VLAN" max={256} onAdd={() => add('vlans', NEW_ROWS.vlans)} onRemove={(i) => remove('vlans', i)}
            render={(v, i) => (
              <>
                <Input label="VLAN ID" value={v.id} onChange={(x) => set(`vlans.${i}.id`, x)} error={e(`vlans.${i}.id`)} inputMode="numeric" />
                <Input label="Name" value={v.name} onChange={(x) => set(`vlans.${i}.name`, x)} error={e(`vlans.${i}.name`)} maxLength={32} />
              </>
            )}
          />
        </Section>
      )}

      {has('access') && (
        <Section id="access" title="Access ports" hint={`One VLAN per group of ports. ${portHint}`} error={exact('access')}>
          <Rows items={form.access} addLabel="Add port group" max={48} onAdd={() => add('access', NEW_ROWS.access)} onRemove={(i) => remove('access', i)}
            render={(a, i) => (
              <div className="stack">
                <div className="form-grid">
                  <Input label="Ports" value={a.interfaces} onChange={(x) => set(`access.${i}.interfaces`, x)} error={e(`access.${i}.interfaces`)} placeholder="Gi1/0/1-12, Gi1/0/20" mono />
                  <Input label="VLAN" value={a.vlan} onChange={(x) => set(`access.${i}.vlan`, x)} error={e(`access.${i}.vlan`)} inputMode="numeric" />
                  <Input label="Description" value={a.description} onChange={(x) => set(`access.${i}.description`, x)} error={e(`access.${i}.description`)} maxLength={80} />
                </div>
                <div className="row">
                  <Check label="PortFast (end hosts only)" checked={a.portfast} onChange={(x) => set(`access.${i}.portfast`, x)} />
                  <Check label="Port security" checked={a.port_security} onChange={(x) => set(`access.${i}.port_security`, x)} />
                </div>
                {a.port_security && (
                  <div className="form-grid">
                    <Input label="Max MAC addresses" value={a.ps_max} onChange={(x) => set(`access.${i}.ps_max`, x)} error={e(`access.${i}.port_security.maximum`)} inputMode="numeric" />
                    <Select label="On violation" value={a.ps_violation} onChange={(x) => set(`access.${i}.ps_violation`, x)} options={[['shutdown', 'Shut the port down'], ['restrict', 'Drop and log'], ['protect', 'Drop silently']]} />
                    <Check label="Sticky MAC addresses" checked={a.ps_sticky} onChange={(x) => set(`access.${i}.ps_sticky`, x)} />
                  </div>
                )}
              </div>
            )}
          />
        </Section>
      )}

      {has('trunk') && (
        <Section id="trunks" title="Trunks" hint="Links to other switches. The allowed list is written exactly." error={exact('trunks')}>
          <Rows items={form.trunks} addLabel="Add trunk" max={48} onAdd={() => add('trunks', NEW_ROWS.trunks)} onRemove={(i) => remove('trunks', i)}
            render={(t, i) => (
              <>
                <Input label="Port" value={t.interface} onChange={(x) => set(`trunks.${i}.interface`, x)} error={e(`trunks.${i}.interface`)} mono />
                <Input label="Allowed VLANs" value={t.allowed} onChange={(x) => set(`trunks.${i}.allowed`, x)} error={e(`trunks.${i}.allowed_vlans`)} placeholder="10,20,30-35" mono />
                <Input label="Native VLAN" value={t.native} onChange={(x) => set(`trunks.${i}.native`, x)} error={e(`trunks.${i}.native_vlan`)} inputMode="numeric" />
                <Input label="Description" value={t.description} onChange={(x) => set(`trunks.${i}.description`, x)} error={e(`trunks.${i}.description`)} maxLength={80} />
              </>
            )}
          />
        </Section>
      )}

      {has('svi') && (
        <Section id="svis" title="VLAN interfaces (SVIs)" hint="Gateway addresses; IP routing is turned on for you." error={exact('svis')}>
          <Rows items={form.svis} addLabel="Add SVI" max={64} onAdd={() => add('svis', NEW_ROWS.svis)} onRemove={(i) => remove('svis', i)}
            render={(s, i) => (
              <>
                <Input label="VLAN" value={s.vlan} onChange={(x) => set(`svis.${i}.vlan`, x)} error={e(`svis.${i}.vlan`)} inputMode="numeric" />
                <Input label="Address/prefix" value={s.ip} onChange={(x) => set(`svis.${i}.ip`, x)} error={e(`svis.${i}.ip`)} placeholder="10.0.10.1/24" mono />
                <Input label="Description" value={s.description} onChange={(x) => set(`svis.${i}.description`, x)} error={e(`svis.${i}.description`)} maxLength={80} />
              </>
            )}
          />
        </Section>
      )}

      {has('routed_if') && (
        <Section id="interfaces" title="Routed interfaces" hint={`Physical ports or Loopback interfaces with an IP address. ${portHint}`} error={exact('interfaces')}>
          <Rows items={form.interfaces} addLabel="Add interface" max={48} onAdd={() => add('interfaces', NEW_ROWS.interfaces)} onRemove={(i) => remove('interfaces', i)}
            render={(r, i) => (
              <>
                <Input label="Interface" value={r.interface} onChange={(x) => set(`interfaces.${i}.interface`, x)} error={e(`interfaces.${i}.interface`)} mono />
                <Input label="Address/prefix" value={r.ip} onChange={(x) => set(`interfaces.${i}.ip`, x)} error={e(`interfaces.${i}.ip`)} placeholder="10.255.0.1/30" mono />
                <Input label="Description" value={r.description} onChange={(x) => set(`interfaces.${i}.description`, x)} error={e(`interfaces.${i}.description`)} maxLength={80} />
              </>
            )}
          />
        </Section>
      )}

      {has('dhcp') && (
        <Section id="dhcp" title="DHCP server" hint="The gateway must be inside the pool network." error={exact('dhcp')}>
          <Rows items={form.dhcp} addLabel="Add pool" max={32} onAdd={() => add('dhcp', NEW_ROWS.dhcp)} onRemove={(i) => remove('dhcp', i)}
            render={(d, i) => (
              <div className="form-grid">
                <Input label="Pool name" value={d.name} onChange={(x) => set(`dhcp.${i}.name`, x)} error={e(`dhcp.${i}.name`)} maxLength={32} />
                <Input label="Network" value={d.network} onChange={(x) => set(`dhcp.${i}.network`, x)} error={e(`dhcp.${i}.network`)} placeholder="10.0.20.0/24" mono />
                <Input label="Gateway" value={d.default_router} onChange={(x) => set(`dhcp.${i}.default_router`, x)} error={e(`dhcp.${i}.default_router`)} placeholder="10.0.20.1" mono />
                <Input label="DNS servers" value={d.dns} onChange={(x) => set(`dhcp.${i}.dns`, x)} error={e(`dhcp.${i}.dns_servers`)} placeholder="9.9.9.9, 1.1.1.1" mono />
                <Input label="Domain" value={d.domain} onChange={(x) => set(`dhcp.${i}.domain`, x)} error={e(`dhcp.${i}.domain`)} />
                <Input label="Lease (days)" value={d.lease_days} onChange={(x) => set(`dhcp.${i}.lease_days`, x)} error={e(`dhcp.${i}.lease_days`)} inputMode="numeric" />
                <Input label="Excluded addresses" value={d.excluded} onChange={(x) => set(`dhcp.${i}.excluded`, x)} error={e(`dhcp.${i}.excluded`)} placeholder="10.0.20.1-10.0.20.9, 10.0.20.254" mono />
              </div>
            )}
          />
        </Section>
      )}

      {has('nat') && (
        <Section id="nat" title="NAT overload (PAT)" hint="Share the outside interface's address with the inside networks." on={form.nat.on} onToggle={(v) => set('nat.on', v)} error={exact('nat')}>
          <div className="form-grid">
            <Input label="Inside interfaces" value={form.nat.inside} onChange={(v) => set('nat.inside', v)} error={e('nat.inside_interfaces')} mono />
            <Input label="Outside interface" value={form.nat.outside} onChange={(v) => set('nat.outside', v)} error={e('nat.outside_interface')} mono />
            <Input label="Inside networks" value={form.nat.networks} onChange={(v) => set('nat.networks', v)} error={e('nat.inside_networks')} placeholder="10.0.0.0/24" mono />
          </div>
        </Section>
      )}

      {has('static') && (
        <Section id="statics" title="Static routes" hint="Next hop address or exit interface." error={exact('statics')}>
          <Rows items={form.statics} addLabel="Add route" max={64} onAdd={() => add('statics', NEW_ROWS.statics)} onRemove={(i) => remove('statics', i)}
            render={(s, i) => (
              <>
                <Input label="Prefix" value={s.prefix} onChange={(x) => set(`statics.${i}.prefix`, x)} error={e(`statics.${i}.prefix`) || exact(`statics.${i}`)} placeholder="0.0.0.0/0" mono />
                <Input label="Next hop or interface" value={s.target} onChange={(x) => set(`statics.${i}.target`, x)} error={e(`statics.${i}.next_hop`) || e(`statics.${i}.interface`)} mono />
                <Input label="Distance" value={s.distance} onChange={(x) => set(`statics.${i}.distance`, x)} error={e(`statics.${i}.distance`)} inputMode="numeric" />
              </>
            )}
          />
        </Section>
      )}

      {has('ospf') && (
        <Section id="ospf" title="OSPF" hint="Interfaces join by exact address, so their IPs must be in this plan." on={form.ospf.on} onToggle={(v) => set('ospf.on', v)} error={exact('routing.ospf')}>
          <div className="form-grid">
            <Input label="Process ID" value={form.ospf.process_id} onChange={(v) => set('ospf.process_id', v)} error={e('routing.ospf.process_id')} inputMode="numeric" />
            <Input label="Router ID" value={form.ospf.router_id} onChange={(v) => set('ospf.router_id', v)} error={e('routing.ospf.router_id')} placeholder="10.255.255.1" mono />
            <Input label="Passive interfaces" value={form.ospf.passive} onChange={(v) => set('ospf.passive', v)} error={e('routing.ospf.passive_interfaces')} mono />
          </div>
          <Rows items={form.ospf.interfaces} addLabel="Add OSPF interface" max={64}
            onAdd={() => setForm((f) => ({ ...f, ospf: { ...f.ospf, interfaces: [...f.ospf.interfaces, NEW_ROWS.ospfInterfaces()] } }))}
            onRemove={(i) => setForm((f) => ({ ...f, ospf: { ...f.ospf, interfaces: f.ospf.interfaces.filter((_, j) => j !== i) } }))}
            render={(o, i) => (
              <>
                <Input label="Interface" value={o.interface} onChange={(x) => set(`ospf.interfaces.${i}.interface`, x)} error={e(`routing.ospf.interfaces.${i}.interface`)} mono />
                <Input label="Area" value={o.area} onChange={(x) => set(`ospf.interfaces.${i}.area`, x)} error={e(`routing.ospf.interfaces.${i}.area`)} inputMode="numeric" />
              </>
            )}
          />
        </Section>
      )}

      {has('eigrp') && (
        <Section id="eigrp" title="EIGRP (classic mode)" on={form.eigrp.on} onToggle={(v) => set('eigrp.on', v)} error={exact('routing.eigrp')}>
          <div className="form-grid">
            <Input label="AS number" value={form.eigrp.asn} onChange={(v) => set('eigrp.asn', v)} error={e('routing.eigrp.asn')} inputMode="numeric" />
            <Input label="Router ID" value={form.eigrp.router_id} onChange={(v) => set('eigrp.router_id', v)} error={e('routing.eigrp.router_id')} mono />
            <Input label="Networks" value={form.eigrp.networks} onChange={(v) => set('eigrp.networks', v)} error={e('routing.eigrp.networks')} placeholder="10.0.0.0/24, 10.255.0.0/30" mono />
            <Input label="Passive interfaces" value={form.eigrp.passive} onChange={(v) => set('eigrp.passive', v)} error={e('routing.eigrp.passive_interfaces')} mono />
          </div>
        </Section>
      )}

      {has('bgp') && (
        <Section id="bgp" title="BGP (eBGP neighbours)" on={form.bgp.on} onToggle={(v) => set('bgp.on', v)} error={exact('routing.bgp')}>
          <div className="form-grid">
            <Input label="Local AS" value={form.bgp.asn} onChange={(v) => set('bgp.asn', v)} error={e('routing.bgp.asn')} inputMode="numeric" />
            <Input label="Router ID" value={form.bgp.router_id} onChange={(v) => set('bgp.router_id', v)} error={e('routing.bgp.router_id')} mono />
            <Input label="Announced networks" value={form.bgp.networks} onChange={(v) => set('bgp.networks', v)} error={e('routing.bgp.networks')} placeholder="198.51.100.0/24" mono />
          </div>
          <Rows items={form.bgp.neighbors} addLabel="Add neighbour" max={32}
            onAdd={() => setForm((f) => ({ ...f, bgp: { ...f.bgp, neighbors: [...f.bgp.neighbors, NEW_ROWS.bgpNeighbors()] } }))}
            onRemove={(i) => setForm((f) => ({ ...f, bgp: { ...f.bgp, neighbors: f.bgp.neighbors.filter((_, j) => j !== i) } }))}
            render={(n, i) => (
              <>
                <Input label="Neighbour IP" value={n.ip} onChange={(x) => set(`bgp.neighbors.${i}.ip`, x)} error={e(`routing.bgp.neighbors.${i}.ip`)} mono />
                <Input label="Remote AS" value={n.remote_as} onChange={(x) => set(`bgp.neighbors.${i}.remote_as`, x)} error={e(`routing.bgp.neighbors.${i}.remote_as`)} inputMode="numeric" />
                <Input label="Description" value={n.description} onChange={(x) => set(`bgp.neighbors.${i}.description`, x)} error={e(`routing.bgp.neighbors.${i}.description`)} maxLength={80} />
              </>
            )}
          />
        </Section>
      )}

      <Section id="custom" title="Custom commands" hint="One command per line, sent as typed after the generated commands. Checked against the denylist and written to the audit log." error={exact('custom_commands') || e('commands')}>
        {production ? (
          <Alert tone="warning">Custom commands are not allowed on production devices.</Alert>
        ) : (
          <Field label="Commands" error={e('custom_commands')}>
            {(props) => (
              <textarea {...props} className="textarea" rows={4} value={form.custom} spellCheck={false} onChange={(ev) => set('custom', ev.target.value)} />
            )}
          </Field>
        )}
      </Section>

      <Section id="options" title="Push options">
        <div className="form-grid">
          <Input label="Automatic rollback after (minutes)" value={form.revert_minutes} onChange={(v) => set('revert_minutes', v)} error={e('revert_minutes')} hint="The device restores its old configuration unless the change is confirmed in time." inputMode="numeric" />
        </div>
        <Check label="Save to startup configuration after a successful check" checked={form.save} onChange={(v) => set('save', v)} />
      </Section>
    </div>
  )
}
