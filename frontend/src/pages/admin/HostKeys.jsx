import { useCallback, useEffect, useState } from 'react'
import { KeyRound, ShieldAlert, Trash2 } from 'lucide-react'
import { del, get, post } from '../../lib/api.js'
import { Alert, Badge, Dialog, Empty, ErrorNote, PageHeader, Panel, SkeletonRows, formatDate } from '../../components/ui.jsx'

/**
 * SSH host keys pinned on first use (trust on first use, like PuTTY's "store key in cache?").
 * If a device later offers a different key, the push is refused before the password is sent and the new key
 * waits here until an admin checks it on the device console and accepts it.
 */
export default function HostKeys() {
  const [keys, setKeys] = useState(null)
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(null) // { kind: 'accept' | 'forget', key }
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get('/hostkeys').then(setKeys).catch(setError)
  }, [])
  useEffect(load, [load])

  async function act() {
    const { kind, key } = confirm
    setBusy(true)
    setError(null)
    try {
      if (kind === 'accept') await post(`/hostkeys/${key.id}/accept`)
      else await del(`/hostkeys/${key.id}`)
      setConfirm(null)
      load()
    } catch (err) {
      setError(err)
      setConfirm(null)
    } finally {
      setBusy(false)
    }
  }

  const pending = keys?.filter((k) => k.pending) || []
  return (
    <>
      <PageHeader title="SSH host keys" subtitle="Each device's key is stored on first connection. A changed key blocks pushes until you accept it." />
      <ErrorNote error={error} />
      {pending.length > 0 && (
        <Alert tone="danger" title={`${pending.length} device${pending.length > 1 ? 's' : ''} offered a different key.`}>
          This happens after a device is replaced or its keys are regenerated – or during a man-in-the-middle attack.
          Compare the new fingerprint with the one shown on the device's console before accepting it.
        </Alert>
      )}
      <Panel title="Known hosts">
        {!keys ? (
          <SkeletonRows rows={4} />
        ) : keys.length === 0 ? (
          <Empty icon={KeyRound} title="No host keys yet">A key is stored the first time a push connects to a device over SSH.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Host</th>
                  <th scope="col">Pinned key</th>
                  <th scope="col">Seen</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id}>
                    <td className="mono">{k.host}:{k.port}</td>
                    <td>
                      <div className="faint">{k.key_type}</div>
                      <div className="fingerprint">{k.fingerprint}</div>
                      {k.pending && (
                        <div className="stack" style={{ marginTop: 8 }}>
                          <Badge tone="danger"><ShieldAlert size={14} aria-hidden="true" /> new key offered {formatDate(k.pending.seen_at)}</Badge>
                          <div className="faint">{k.pending.key_type}</div>
                          <div className="fingerprint">{k.pending.fingerprint}</div>
                        </div>
                      )}
                    </td>
                    <td className="faint" style={{ whiteSpace: 'nowrap' }}>
                      first {formatDate(k.first_seen)}<br />last {formatDate(k.last_seen)}
                      {k.accepted_by && <><br />accepted by {k.accepted_by.username}</>}
                    </td>
                    <td>
                      <div className="row">
                        {k.pending && (
                          <button type="button" className="btn small primary" onClick={() => setConfirm({ kind: 'accept', key: k })}>
                            Accept new key
                          </button>
                        )}
                        <button type="button" className="btn small ghost" onClick={() => setConfirm({ kind: 'forget', key: k })}
                          aria-label={`Forget the key of ${k.host}:${k.port}`}>
                          <Trash2 size={16} aria-hidden="true" /> Forget
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {confirm && (
        <Dialog title={confirm.kind === 'accept' ? 'Accept the new host key?' : 'Forget this host key?'} onClose={() => setConfirm(null)}>
          <div className="stack">
            {confirm.kind === 'accept' ? (
              <>
                <p>Only accept if this fingerprint matches the one the device itself shows:</p>
                <p className="fingerprint">{confirm.key.pending.fingerprint}</p>
              </>
            ) : (
              <p>
                The next connection to {confirm.key.host}:{confirm.key.port} will trust whatever key it is offered
                (trust on first use). Do this only when you know the device was replaced.
              </p>
            )}
            <div className="form-actions">
              <button type="button" className="btn" onClick={() => setConfirm(null)}>Keep as is</button>
              <button type="button" className={`btn ${confirm.kind === 'accept' ? 'primary' : 'danger'}`} disabled={busy} onClick={act}>
                {confirm.kind === 'accept' ? 'Accept new key' : 'Forget key'}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  )
}
