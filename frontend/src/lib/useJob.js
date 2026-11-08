import { useCallback, useEffect, useRef, useState } from 'react'
import { get } from './api.js'
import { pollDelay } from './jobs.js'

/**
 * Load a job and keep it fresh: every second while it is pushing, every 5 s while it waits for a person,
 * and not at all once it has finished. `setJob` lets callers apply the response of an action at once.
 */
export function useJob(jobId, initial = null) {
  const [job, setJob] = useState(initial)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const load = useCallback(
    async (signal) => {
      try {
        const doc = await get(`/jobs/${jobId}`, { signal })
        setJob(doc)
        setError(null)
        return doc
      } catch (err) {
        if (err.name !== 'AbortError') setError(err)
        return null
      }
    },
    [jobId],
  )

  const status = job?.status
  useEffect(() => {
    if (!jobId) return undefined
    const ctrl = new AbortController()
    // First load (or a status change): fetch now unless we already have this job, then poll if needed.
    const delay = job?.id === jobId ? pollDelay(status) : 0
    if (delay === null) return () => ctrl.abort()
    timer.current = setTimeout(async function tick() {
      const doc = await load(ctrl.signal)
      const next = pollDelay(doc?.status ?? status)
      // A changed status re-runs this effect (new chain); a failed load keeps polling at the old pace.
      if (next !== null && !ctrl.signal.aborted && (!doc || doc.status === status)) {
        timer.current = setTimeout(tick, next)
      }
    }, delay)
    return () => {
      ctrl.abort()
      clearTimeout(timer.current)
    }
    // `job` is read only to know whether the first load happened; the status drives the polling.
  }, [jobId, status, load])

  return { job, setJob, error, reload: () => load() }
}
