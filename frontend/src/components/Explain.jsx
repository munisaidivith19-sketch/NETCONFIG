import { useEffect, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { explain, useAiStatus } from '../lib/ai.js'
import { useAuth } from '../lib/auth.jsx'
import { ErrorNote } from './ui.jsx'

const LABELS = { commands: 'Explain these commands', verification: 'Explain this failure', diff: 'Explain the differences' }

/**
 * "Explain" button for a command block, a failed verification or a config diff. The backend masks the text again
 * before it goes to the model and treats it as untrusted data. The answer is shown as plain text (React escapes
 * it) and nothing in the app acts on it. Hidden when the assistant is off or the user is a viewer.
 */
export default function Explain({ kind, text }) {
  const ai = useAiStatus()
  const { can } = useAuth()
  const [answer, setAnswer] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // A different text (next device, edited plan) makes the old answer wrong.
  useEffect(() => {
    setAnswer(null)
    setError(null)
  }, [text])

  if (!ai?.enabled || !can('engineer') || !text?.trim()) return null

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setAnswer(await explain(kind, text))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="row">
        <button type="button" className="btn small ghost" onClick={run} disabled={busy}>
          {busy ? <Loader2 size={16} aria-hidden="true" className="spin" /> : <Sparkles size={16} aria-hidden="true" />}
          {busy ? 'Asking the assistant…' : LABELS[kind]}
        </button>
      </div>
      <div aria-live="polite">
        {answer && (
          <div className="ai-answer">
            <p className="faint ai-note">
              AI explanation ({ai.provider}) – it can be wrong, so check it against the commands.
              {answer.cut && ' Only the first part of a long text was sent.'}
            </p>
            <p className="ai-text">{answer.text}</p>
          </div>
        )}
        <ErrorNote error={error} />
      </div>
    </div>
  )
}
