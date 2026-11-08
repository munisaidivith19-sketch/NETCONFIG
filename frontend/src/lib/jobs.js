// Push-job helpers shared by Configure (steps 4–5), History and the job detail page.
// The backend owns the state machine (backend/app/services/jobs.py); this file only describes it for display.

export const RUNNING = ['queued', 'connecting', 'backing_up', 'checking', 'applying', 'verifying', 'saving', 'rolling_back']
export const TERMINAL = ['success', 'failed', 'rolled_back', 'blocked', 'cancelled', 'expired']
export const CANCELLABLE = ['awaiting_approval', 'ready', 'queued', 'connecting', 'backing_up', 'checking']

export const STATUS = {
  awaiting_approval: { label: 'Awaiting approval', tone: 'warning' },
  ready: { label: 'Ready to run', tone: 'info' },
  queued: { label: 'Queued', tone: 'info' },
  connecting: { label: 'Connecting', tone: 'info' },
  backing_up: { label: 'Backing up', tone: 'info' },
  checking: { label: 'Pre-checks', tone: 'info' },
  applying: { label: 'Applying', tone: 'info' },
  verifying: { label: 'Verifying', tone: 'info' },
  saving: { label: 'Saving', tone: 'info' },
  rolling_back: { label: 'Rolling back', tone: 'warning' },
  success: { label: 'Success', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  rolled_back: { label: 'Rolled back', tone: 'warning' },
  blocked: { label: 'Blocked', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: '' },
  expired: { label: 'Expired', tone: '' },
}
export const statusLabel = (s) => STATUS[s]?.label || s
export const statusTone = (s) => STATUS[s]?.tone ?? ''

export const isRunning = (s) => RUNNING.includes(s)
export const isTerminal = (s) => TERMINAL.includes(s)

// The phases of one push, in order, as shown in the progress list.
export const PHASES = [
  ['connecting', 'Connect (SSH host key checked)'],
  ['backing_up', 'Back up the running config'],
  ['checking', 'Pre-checks: management interface, denylist'],
  ['applying', 'Apply inside the rollback timer'],
  ['verifying', 'Verify with show commands'],
  ['saving', 'Confirm and save'],
]

/**
 * State of every phase from the job's timeline: 'done' | 'active' | 'failed' | 'pending'.
 * The last phase reached is 'failed' when the job ended badly (failed, blocked, rolled back).
 */
export function phaseStates(job) {
  const step = job?.steps?.[0]
  const reached = new Set((step?.timeline || []).map((t) => t.state))
  const status = job?.status
  const bad = ['failed', 'blocked', 'rolled_back', 'rolling_back'].includes(status)
  const lastReached = [...PHASES].reverse().find(([id]) => reached.has(id))?.[0]
  return PHASES.map(([id, label]) => {
    let state = 'pending'
    if (reached.has(id)) {
      if (id === status) state = 'active'
      else if (bad && id === lastReached) state = 'failed'
      else state = 'done'
    }
    if (status === 'success' && reached.has(id)) state = 'done'
    return { id, label, state }
  })
}

/** Which run-time secrets the stored plan needs (the plan itself never holds them). */
export function secretsNeeded(plan) {
  return {
    sshUser: plan?.ssh?.username || null,
    enableSecret: Boolean(plan?.ssh?.set_enable_secret),
  }
}

// Same allowlist as the backend's JobCreate.note and RejectRequest.reason (no CLI-special characters).
export const NOTE_PATTERN = /^[A-Za-z0-9 _.,:/()@+=!'-]*$/
export const NOTE_HINT = "Letters, digits, spaces and . , : / ( ) @ + = ! ' - only"

// Same rule as the backend's DevicePassword: 8–64 characters, no spaces or # ? ; | " ' ^
const BAD_SECRET = /[\s#?;|"'^]/
export function checkNewSecret(value, confirm) {
  if (!value) return 'Required'
  if (value.length < 8 || value.length > 64) return 'Use 8 to 64 characters'
  if (BAD_SECRET.test(value)) return 'No spaces or any of # ? ; | " \' ^ (they break the device CLI)'
  if (value !== confirm) return 'The two entries do not match'
  return null
}

/** Poll delay: every second while pushing, slower while waiting for a person. null = stop. */
export function pollDelay(status) {
  if (isRunning(status)) return 1000
  if (status === 'awaiting_approval' || status === 'ready') return 5000
  return null
}
