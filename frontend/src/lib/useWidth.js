import { useLayoutEffect, useRef, useState } from 'react'

// Width of an element in CSS pixels, kept up to date with ResizeObserver. SVG charts and the network map draw
// at this width (1:1) instead of scaling a fixed viewBox, so text and touch targets keep their real size on a
// phone. Falls back to `fallback` where ResizeObserver does not exist (tests).
export function useWidth(fallback, min = 280) {
  const ref = useRef(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) setWidth(Math.max(min, w))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [min])
  return [ref, width]
}
