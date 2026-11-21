// AI assistant helpers (Phase 5A). The assistant is optional: when the backend says it is off, nothing AI-related
// is shown. A draft only pre-fills the form; it is validated and previewed like a manual plan.
import { useEffect, useState } from 'react'
import { get, post } from './api.js'

export const MAX_EXPLAIN_CHARS = 6000 // the backend's limit; longer texts are cut and the answer says so
export const DRAFT_MIN = 10
export const DRAFT_MAX = 2000

let statusRequest = null

/** GET /ai/status once per page load (a failed request is retried next time). */
export function loadAiStatus() {
  statusRequest ??= get('/ai/status').catch(() => {
    statusRequest = null
    return { enabled: false }
  })
  return statusRequest
}

export function resetAiStatus() {
  statusRequest = null // tests, and after logging in again
}

export function useAiStatus() {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    let live = true
    loadAiStatus().then((s) => live && setStatus(s))
    return () => { live = false }
  }, [])
  return status
}

export function explain(kind, text) {
  const cut = text.length > MAX_EXPLAIN_CHARS
  return post('/ai/explain', { kind, text: text.slice(0, MAX_EXPLAIN_CHARS) }).then((r) => ({ text: r.text, cut }))
}

export const draftPlan = (description) => post('/ai/draft', { description })

// Plan keys per capability (the names PlanForm uses to show a section).
const FEATURE_KEYS = {
  vlans: ['vlans'], access: ['access'], trunk: ['trunks'], svi: ['svis'], routed_if: ['interfaces'], dhcp: ['dhcp'],
  nat: ['nat'], static: ['statics'], default_gateway: ['default_gateway'],
  ospf: ['routing', 'ospf'], eigrp: ['routing', 'eigrp'], bgp: ['routing', 'bgp'],
}

/**
 * Keep only what the chosen device can do, so the draft never fills a section the form hides. What was taken out
 * is returned and shown to the engineer (never dropped silently).
 */
export function onlySupported(plan, features, caps, category) {
  const out = { ...plan, routing: plan.routing ? { ...plan.routing } : plan.routing }
  const removed = []
  for (const f of features) {
    const keys = FEATURE_KEYS[f]
    if (!keys) continue
    const ok = caps.has(f) && (f !== 'default_gateway' || category === 'switch')
    if (ok) continue
    removed.push(f)
    if (keys.length === 1) out[keys[0]] = Array.isArray(plan[keys[0]]) ? [] : null
    else if (out.routing) out.routing[keys[1]] = null
  }
  return { plan: out, removed }
}
