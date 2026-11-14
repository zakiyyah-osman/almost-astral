// Web Worker for the whole-crater grid (craterTasks.js). It fetches and parses the grid files itself,
// so the page's main thread never touches them. Messages in: { id, type, args }; out: { id, ok, result }
// or { id, ok: false, error }. 'load' takes { base, headerFile, params, site, radRows, backgroundUsvH }.
import { createCraterState, runCraterTask } from './craterTasks.js'

const state = createCraterState()

async function load({ base, headerFile, ...rest }) {
  const get = async (file, as) => {
    const r = await fetch(new URL(file, base))
    if (!r.ok) throw new Error(`${file}: ${r.status}`)
    return as === 'json' ? r.json() : r.arrayBuffer()
  }
  const t0 = performance.now()
  const header = await get(headerFile, 'json')
  const [height, hazard, slope] = await Promise.all([get(header.height.file), get(header.hazard.file), get(header.slope.file)])
  const t1 = performance.now()
  const info = runCraterTask(state, 'load', { header, height, hazard, slope, ...rest })
  return { ...info, fetchMs: Math.round(t1 - t0), buildMs: Math.round(performance.now() - t1) }
}

self.onmessage = async ({ data: { id, type, args } }) => {
  try {
    const result = type === 'load' ? await load(args) : runCraterTask(state, type, args)
    self.postMessage({ id, ok: true, result })
  } catch (e) {
    self.postMessage({ id, ok: false, error: String(e?.message ?? e) })
  }
  // A probe asked for minutes back that are not worked out yet: do it now, after the answer has gone.
  if (state.wantShelters) {
    const shelters = state.wantShelters
    state.wantShelters = null
    setTimeout(() => {
      try {
        runCraterTask(state, 'field', { shelters })
      } catch {
        /* the next probe or route will try again */
      }
    }, 0)
  }
}
