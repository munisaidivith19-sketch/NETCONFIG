// Live data for the Overview and Topology pages (GET /api/overview): loads once, refreshes every 30 s while the
// tab is visible, and "Check status now" asks the server to check every device at once.
import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from './api.js'

const REFRESH_MS = 30000

export function useOverview() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)
  const [notice, setNotice] = useState(null)

  // Background refresh keeps the current frame on screen (no flash, no skeleton) and only swaps the numbers.
  const load = useCallback(() => get('/overview').then((d) => { setData(d); setError(null) }).catch(setError), [])

  const recheck = useRef(null) // timer of "Check status now"
  useEffect(() => () => clearTimeout(recheck.current), [])

  useEffect(() => {
    load()
    // No polling while the tab is hidden; coming back refreshes at once.
    const t = setInterval(() => { if (!document.hidden) load() }, REFRESH_MS)
    const onShow = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', onShow)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onShow) }
  }, [load])

  const refresh = useCallback(async () => {
    setNotice(null)
    setChecking(true)
    try {
      await post('/overview/refresh')
      setNotice('Checking every device now. The map updates in a few seconds.')
      recheck.current = setTimeout(() => load().finally(() => setChecking(false)), 5000)
    } catch (err) {
      setError(err)
      setChecking(false)
    }
  }, [load])

  return { data, error, load, checking, notice, refresh }
}
