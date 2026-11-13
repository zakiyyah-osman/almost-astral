// Route finding in the browser, on the site grid. It follows the model in routing/ (Person 3):
// walking speed from Tobler's function normalised to v_flat on flat ground, the same hard limits
// (slope limit, cliff buffer, red cells, sealed diagonal gaps) and the same risk terms, and the
// same three profiles (fastest w = 0, balanced w = 1, safest w = 5). The planner's own route in
// route.geojson stays the reference; this lets the crew try any start and end point live.
import { cellOf, centreOf } from './terrain.js'

// The values in routing/config.toml. plan.json repeats them under `assumptions` when the planner
// has run; paramsFrom() then reads them from there, so a change in config.toml reaches the app.
export const DEFAULT_PARAMS = {
  v_flat_kmh: 2.7,
  tobler_k: 3.5,
  tobler_offset: 0.05,
  slope_max_deg: 20,
  cliff_buffer_m: 5,
  yellow_rate: 1.0,
  steep_onset_deg: 10,
  steep_rate_max: 0.0,
  near_red_radius_m: 15,
  near_red_rate_max: 1.0,
  w_fastest: 0,
  w_balanced: 1,
  w_safest: 5,
  stop_min_default: 25,
  ingress_min: 15,
  eva_max_min: 360,
  reserve_pct: 30,
  radiation_limit_usv: 1000,
}

const KEYS = {
  v_flat_kmh: 'walking.v_flat_kmh',
  tobler_k: 'walking.tobler_k',
  tobler_offset: 'walking.tobler_offset',
  slope_max_deg: 'constraints.slope_max_deg',
  cliff_buffer_m: 'constraints.cliff_buffer_m',
  yellow_rate: 'risk.yellow_rate',
  steep_onset_deg: 'risk.steep_onset_deg',
  steep_rate_max: 'risk.steep_rate_max',
  near_red_radius_m: 'risk.near_red_radius_m',
  near_red_rate_max: 'risk.near_red_rate_max',
  w_fastest: 'profiles.w_fastest',
  w_balanced: 'profiles.w_balanced',
  w_safest: 'profiles.w_safest',
  stop_min_default: 'timeline.stop_min_default',
  ingress_min: 'timeline.ingress_min',
  eva_max_min: 'timeline.eva_max_min',
  reserve_pct: 'timeline.reserve_pct',
  radiation_limit_usv: 'radiation.limit_usv',
}

export const PROFILES = [
  { id: 'fastest', label: 'Fastest', key: 'w_fastest' },
  { id: 'balanced', label: 'Balanced', key: 'w_balanced' },
  { id: 'safest', label: 'Safest', key: 'w_safest' },
]

// Parameters, taking each from plan.json's `assumptions` when present. `from` says where they came from.
export function paramsFrom(plan) {
  const a = plan?.assumptions
  const p = { ...DEFAULT_PARAMS }
  let fromPlan = 0
  if (a && typeof a === 'object') {
    for (const [name, key] of Object.entries(KEYS)) {
      const v = a[key]?.value
      if (typeof v === 'number' && Number.isFinite(v)) {
        p[name] = v
        fromPlan++
      }
    }
  }
  if (plan?.budgets?.eva_max_min) p.eva_max_min = plan.budgets.eva_max_min
  if (plan?.budgets?.radiation_limit_usv) p.radiation_limit_usv = plan.budgets.radiation_limit_usv
  p.from = fromPlan ? 'plan.json (routing/config.toml)' : 'routing/config.toml values copied into the app'
  return p
}

// Walking speed in metres per minute on a slope given as rise over run (routing/walking.py).
export function speedMPerMin(ratio, p) {
  const f = Math.exp(-p.tobler_k * (Math.abs(ratio) + p.tobler_offset)) / Math.exp(-p.tobler_k * p.tobler_offset)
  return ((p.v_flat_kmh * 1000) / 60) * f
}

// Cells within radius metres of any cell where mask is true (distance between cell centres).
function nearMask(mask, width, height, cellM, radiusM) {
  const out = new Uint8Array(mask.length)
  const rc = Math.floor(radiusM / cellM + 1e-9)
  if (rc < 1) return out
  const offs = []
  for (let dr = -rc; dr <= rc; dr++) for (let dc = -rc; dc <= rc; dc++) if (Math.hypot(dr, dc) * cellM <= radiusM + 1e-9) offs.push([dr, dc])
  for (let i = 0; i < mask.length; i++) {
    if (!mask[i]) continue
    const r = Math.floor(i / width)
    const c = i % width
    for (const [dr, dc] of offs) {
      const rr = r + dr
      const cc = c + dc
      if (rr >= 0 && cc >= 0 && rr < height && cc < width) out[rr * width + cc] = 1
    }
  }
  return out
}

// Distance in metres to the nearest true cell, looked up only out to radiusM (Infinity beyond).
function distanceWithin(mask, width, height, cellM, radiusM) {
  const out = new Float64Array(mask.length).fill(Infinity)
  const rc = Math.ceil(radiusM / cellM)
  for (let i = 0; i < mask.length; i++) {
    if (!mask[i]) continue
    const r = Math.floor(i / width)
    const c = i % width
    for (let dr = -rc; dr <= rc; dr++) {
      for (let dc = -rc; dc <= rc; dc++) {
        const rr = r + dr
        const cc = c + dc
        if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
        const d = Math.hypot(dr, dc) * cellM
        const j = rr * width + cc
        if (d < out[j]) out[j] = d
      }
    }
  }
  return out
}

// Free cells squeezed between two blocked cells that touch only at a corner (routing/cost.py).
function sealDiagonalGaps(blocked, width, height) {
  const cur = blocked.slice()
  const at = (r, c) => (r < 0 || c < 0 || r >= height || c >= width ? 0 : cur[r * width + c])
  for (;;) {
    const add = []
    for (let r = 0; r < height; r++) {
      for (let c = 0; c < width; c++) {
        if (cur[r * width + c]) continue
        const n = at(r - 1, c), s = at(r + 1, c), w = at(r, c - 1), e = at(r, c + 1)
        if ((n && w && !at(r - 1, c - 1)) || (n && e && !at(r - 1, c + 1)) || (s && w && !at(r + 1, c - 1)) || (s && e && !at(r + 1, c + 1))) add.push(r * width + c)
      }
    }
    if (!add.length) return cur
    for (const i of add) cur[i] = 1
  }
}

// Everything the search needs, built once per terrain and hazard map.
export function buildCost({ dem, slope, hazard, width, height, cellM, params }) {
  const p = params
  const n = width * height
  const over = new Uint8Array(n)
  const red = new Uint8Array(n)
  const base = new Uint8Array(n)
  for (let i = 0; i < n; i++) {
    over[i] = slope[i] > p.slope_max_deg ? 1 : 0
    red[i] = hazard[i] === 2 ? 1 : 0
    base[i] = !Number.isFinite(dem[i]) || !Number.isFinite(slope[i]) || red[i] || over[i] ? 1 : 0
  }
  const buffer = p.cliff_buffer_m > 0 ? nearMask(over, width, height, cellM, p.cliff_buffer_m) : new Uint8Array(n)
  for (let i = 0; i < n; i++) if (buffer[i]) base[i] = 1
  const blocked = sealDiagonalGaps(base, width, height)

  const nearRed = distanceWithin(red, width, height, cellM, p.near_red_radius_m)
  const timeRate = new Float64Array(n) // minutes per metre
  const riskRate = new Float64Array(n) // risk-minutes per minute
  for (let i = 0; i < n; i++) {
    if (blocked[i]) {
      timeRate[i] = -1
      continue
    }
    timeRate[i] = 1 / speedMPerMin(Math.tan((slope[i] * Math.PI) / 180), p)
    const ramp = Math.min(1, Math.max(0, (slope[i] - p.steep_onset_deg) / (p.slope_max_deg - p.steep_onset_deg)))
    const near = Math.max(0, 1 - nearRed[i] / p.near_red_radius_m)
    riskRate[i] = (hazard[i] === 1 ? p.yellow_rate : 0) + p.steep_rate_max * ramp + p.near_red_rate_max * (Number.isFinite(near) ? near : 0)
  }
  return { width, height, cellM, dem, slope, hazard, blocked, timeRate, riskRate, params: p }
}

// Min-heap of [key, value] pairs.
class Heap {
  constructor() {
    this.k = []
    this.v = []
  }
  get size() {
    return this.k.length
  }
  push(key, val) {
    const k = this.k
    const v = this.v
    let i = k.length
    k.push(key)
    v.push(val)
    while (i > 0) {
      const p = (i - 1) >> 1
      if (k[p] <= key) break
      k[i] = k[p]
      v[i] = v[p]
      i = p
    }
    k[i] = key
    v[i] = val
  }
  pop() {
    const k = this.k
    const v = this.v
    const topV = v[0]
    const lastK = k.pop()
    const lastV = v.pop()
    if (k.length) {
      let i = 0
      const n = k.length
      for (;;) {
        let c = 2 * i + 1
        if (c >= n) break
        if (c + 1 < n && k[c + 1] < k[c]) c++
        if (k[c] >= lastK) break
        k[i] = k[c]
        v[i] = v[c]
        i = c
      }
      k[i] = lastK
      v[i] = lastV
    }
    return topV
  }
}

const NEIGH = [
  [-1, 0, 1], [1, 0, 1], [0, -1, 1], [0, 1, 1],
  [-1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [1, 1, Math.SQRT2],
]

// The nearest walkable cell to (x, y), searching out to maxM metres. Returns { i, movedM } or null.
export function snapToFree(cost, x, y, maxM = 100) {
  const { width, height, cellM, blocked } = cost
  const cx = Math.min(width * cellM - 1e-6, Math.max(0, x))
  const cy = Math.min(height * cellM - 1e-6, Math.max(0, y))
  const home = cellOf(cx, cy, width, height, cellM)
  if (!home) return null
  if (!blocked[home.i]) return { i: home.i, movedM: Math.hypot(cx - x, cy - y) }
  const rc = Math.ceil(maxM / cellM)
  let best = null
  for (let dr = -rc; dr <= rc; dr++) {
    for (let dc = -rc; dc <= rc; dc++) {
      const r = home.row + dr
      const c = home.col + dc
      if (r < 0 || c < 0 || r >= height || c >= width) continue
      const i = r * width + c
      if (blocked[i]) continue
      const [px, py] = centreOf(i, width, height, cellM)
      const d = Math.hypot(px - x, py - y)
      if (d <= maxM && (!best || d < best.movedM)) best = { i, movedM: d }
    }
  }
  return best
}

// Least-cost path from cell a to cell b with risk weight w (A*; cost = time x (1 + w x risk),
// averaged over the two cells of each step, like skimage MCP_Geometric). Returns cell indices or null.
export function searchPath(cost, a, b, w) {
  const { width, height, cellM, blocked, timeRate, riskRate, params } = cost
  if (blocked[a] || blocked[b]) return null
  const n = width * height
  const g = new Float64Array(n).fill(Infinity)
  const from = new Int32Array(n).fill(-1)
  const done = new Uint8Array(n)
  const minRate = 1 / speedMPerMin(0, params) // fastest possible: flat ground, no risk
  const br = Math.floor(b / width)
  const bc = b % width
  const h = (i) => Math.hypot(Math.floor(i / width) - br, (i % width) - bc) * cellM * minRate
  const rate = (i) => timeRate[i] * (1 + w * riskRate[i])
  const heap = new Heap()
  g[a] = 0
  heap.push(h(a), a)
  while (heap.size) {
    const i = heap.pop()
    if (done[i]) continue
    done[i] = 1
    if (i === b) break
    const r = Math.floor(i / width)
    const c = i % width
    const ri = rate(i)
    for (const [dr, dc, f] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (blocked[j] || done[j]) continue
      const ng = g[i] + ((ri + rate(j)) / 2) * f * cellM
      if (ng < g[j]) {
        g[j] = ng
        from[j] = i
        heap.push(ng + h(j), j)
      }
    }
  }
  if (!done[b]) return null
  const path = [b]
  while (path[path.length - 1] !== a) path.push(from[path[path.length - 1]])
  return path.reverse()
}

// Walking minutes from cell src to every cell (fastest physical time, no risk weighting).
// Speeds are the same uphill and downhill, so this is also the time from every cell back to src.
export function timeField(cost, src) {
  const { width, height, cellM, blocked, timeRate } = cost
  const n = width * height
  const t = new Float64Array(n).fill(Infinity)
  if (blocked[src]) return t
  const heap = new Heap()
  t[src] = 0
  heap.push(0, src)
  const done = new Uint8Array(n)
  while (heap.size) {
    const i = heap.pop()
    if (done[i]) continue
    done[i] = 1
    const r = Math.floor(i / width)
    const c = i % width
    for (const [dr, dc, f] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (blocked[j] || done[j]) continue
      const nt = t[i] + ((timeRate[i] + timeRate[j]) / 2) * f * cellM
      if (nt < t[j]) {
        t[j] = nt
        heap.push(nt, j)
      }
    }
  }
  return t
}

// Numbers for a path of cells: distance, physical walking time, risk minutes, slope and climb.
export function measurePath(cost, cells) {
  const { width, height, cellM, dem, slope, hazard, timeRate, riskRate } = cost
  let d = 0
  let walk = 0
  let risk = 0
  let ascent = 0
  let descent = 0
  let maxSlope = 0
  const byClass = [0, 0, 0]
  const track = []
  for (let k = 0; k < cells.length; k++) {
    const i = cells[k]
    const [x, y] = centreOf(i, width, height, cellM)
    if (k > 0) {
      const j = cells[k - 1]
      const len = Math.hypot(...centreOf(j, width, height, cellM).map((v, q) => v - [x, y][q]))
      const dt = ((timeRate[i] + timeRate[j]) / 2) * len
      d += len
      walk += dt
      risk += ((riskRate[i] + riskRate[j]) / 2) * dt
      const dz = dem[i] - dem[j]
      if (dz > 0) ascent += dz
      else descent -= dz
      byClass[hazard[i]] += len
    }
    maxSlope = Math.max(maxSlope, slope[i])
    track.push({ i, d, x, y, z: dem[i], slope: slope[i], hazard: hazard[i], t: walk })
  }
  return { distance_m: d, walk_min: walk, risk_min: risk, ascent_m: ascent, descent_m: descent, max_slope_deg: maxSlope, metres_by_class: byClass, track }
}

// Plans one leg from point A to point B ({x, y} metres) with the given profile weight.
export function planLeg(cost, A, B, w) {
  const a = snapToFree(cost, A.x, A.y)
  const b = snapToFree(cost, B.x, B.y)
  if (!a || !b) return { ok: false, reason: !a ? 'start' : 'end' }
  const cells = a.i === b.i ? [a.i] : searchPath(cost, a.i, b.i, w)
  if (!cells) return { ok: false, reason: 'unreachable' }
  const { width, height, cellM } = cost
  return { ok: true, cells, points: cells.map((i) => centreOf(i, width, height, cellM)), snapM: [a.movedM, b.movedM], ...measurePath(cost, cells) }
}
