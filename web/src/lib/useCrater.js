import { useEffect, useRef, useState } from 'react'

// The whole-crater grid in a Web Worker (crater.worker.js), started lazily: a few seconds after the
// page is up, or at once when `wanted` turns true (a point outside the 2 km site). The page never
// parses the grid itself. Returns { status: 'off' | 'loading' | 'ready' | 'error', call, info, error }.
export function useCrater(data, params, rad, wanted) {
  const [state, setState] = useState({ status: 'off' })
  const started = useRef(false)
  const stop = useRef(() => {})
  const headerFile = data?.crater?.grid_header
  // On unmount (and React StrictMode's practice unmount in development) stop the worker and allow a restart.
  useEffect(
    () => () => {
      stop.current()
      stop.current = () => {}
      started.current = false
    },
    [],
  )

  useEffect(() => {
    if (!headerFile || !params || started.current) return
    const start = () => {
      if (started.current) return
      started.current = true
      const worker = new Worker(new URL('./crater.worker.js', import.meta.url), { type: 'module' })
      const pending = new Map()
      let seq = 0
      worker.onmessage = ({ data: { id, ok, result, error } }) => {
        const p = pending.get(id)
        if (!p) return
        pending.delete(id)
        if (ok) p.resolve(result)
        else p.reject(new Error(error))
      }
      const call = (type, args) =>
        new Promise((resolve, reject) => {
          const id = ++seq
          pending.set(id, { resolve, reject })
          worker.postMessage({ id, type, args })
        })
      setState({ status: 'loading' })
      const base = new URL('./', window.location.href).href
      call('load', { base, headerFile, params, site: data.site, ...rad })
        .then((info) => setState({ status: 'ready', call, info }))
        .catch((e) => setState({ status: 'error', error: e.message }))
      stop.current = () => {
        worker.terminate()
        for (const p of pending.values()) p.reject(new Error('crater worker stopped'))
      }
    }
    if (wanted) {
      start()
      return
    }
    const timer = setTimeout(start, 2500) // after the page has drawn: never part of the first load
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headerFile, params, wanted])

  return state
}

// The value of a promise-returning job, recomputed when deps change. While a new value is being worked
// out the previous one stays and busy is true. make() returns null for "nothing to do".
export function useAsync(make, deps) {
  const [state, setState] = useState({ value: null, busy: false })
  useEffect(() => {
    const p = make()
    if (!p) {
      setState({ value: null, busy: false })
      return
    }
    let live = true
    setState((s) => ({ value: s.value, busy: true }))
    p.then((value) => live && setState({ value, busy: false })).catch(() => live && setState({ value: null, busy: false }))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

// The crater terrain at one point (site metres), asked of the worker. Only the latest point counts:
// while one question is out, newer points wait and older answers are dropped.
// Returns { for: point, value } for the last answered point, or null.
export function useCraterProbe(crater, point, shelters) {
  const [answer, setAnswer] = useState(null)
  const busy = useRef(false)
  const next = useRef(null)
  useEffect(() => {
    if (crater.status !== 'ready' || !point) return
    next.current = { point, shelters }
    if (busy.current) return
    const ask = () => {
      const job = next.current
      next.current = null
      if (!job) return
      busy.current = true
      crater
        .call('probe', { x: job.point.x, y: job.point.y, shelters: job.shelters, lazyBack: true })
        .then((value) => setAnswer({ for: job.point, value }))
        .catch(() => setAnswer({ for: job.point, value: null }))
        .finally(() => {
          busy.current = false
          ask()
        })
    }
    ask()
  }, [crater, point, shelters])
  return answer
}
