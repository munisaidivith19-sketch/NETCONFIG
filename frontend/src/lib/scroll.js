// Scroll an element into view, without animation when the user asked for reduced motion.
export function reveal(el, block = 'start') {
  if (!el?.scrollIntoView) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block })
}

// True when panels are stacked in one column (see the 1180 px breakpoint in app.css).
export const stacked = () => Boolean(window.matchMedia?.('(max-width: 1180px)').matches)
