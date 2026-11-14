// Route finding in the browser on routing's exported cost surface (data/out/landing/, read by
// landingData.js). The rule is routing/docs/DESIGN.md section 15, the one the manifest repeats
// under search.edge_rule; golden_cases.json is the test (pathfind.test.js):
//  - planning rate p = time_rate x (1 + w x risk_rate), float64, in that order
//  - 8 neighbours; a cell outside the window or with mask != 0 is never entered
//  - step length cell_m straight, sqrt(cell_m * cell_m + cell_m * cell_m) diagonal
//  - step cost L x (p_a + p_b) / 2; Dijkstra, relax only when strictly less
//  - totals along the path (section 15.3) with step cell_m or cell_m x sqrt(2)
// The cost object comes from costFromLanding (landingData.js); nothing here invents a walking model.

// The values in routing/config.toml, for display only (the Compare tab, the inputs list). plan.json
// repeats them under `assumptions`; paramsFrom() reads them from there. The search never uses them:
// its rates come from routing's time_rate and risk_rate grids.
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
  { id: 'fastest', label: 'Efficient', key: 'w_fastest', aim: 'Shortest walking time' },
  { id: 'balanced', label: 'Balanced', key: 'w_balanced', aim: 'A risky minute counts double' },
  { id: 'safest', label: 'Safe', key: 'w_safest', aim: 'Avoids careful ground hardest' },
]

// Parameters, taking each from plan.json's `assumptions` when present. `from` says where they came from.
// manifest (optional): routing's landing manifest; its profile weights and budget then win, because
// they are what the search and the over-budget rule use.
export function paramsFrom(plan, manifest = null) {
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
  if (manifest?.profiles) for (const pr of PROFILES) if (Number.isFinite(manifest.profiles[pr.id]?.w)) p[pr.key] = manifest.profiles[pr.id].w
  const b = manifest?.budget
  if (b) {
    p.eva_max_min = b.eva_max_min
    p.reserve_pct = b.reserve_pct
    p.ingress_min = b.ingress_min
    p.stop_min_default = b.stop_min
    p.usable_min = b.usable_min
  }
  p.from = fromPlan ? 'plan.json (routing/config.toml)' : 'routing/config.toml values copied into the app'
  return p
}

// Min-heap of [key, value] pairs (also used by lib/escape.js).
export class Heap {
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

// [dRow, dCol, diagonal]
const NEIGH = [
  [-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0],
  [-1, -1, 1], [-1, 1, 1], [1, -1, 1], [1, 1, 1],
]

const origin = (cost) => cost.origin ?? [0, 0]

// The cell holding (x, y), or null outside the grid (manifest layout: row 0 = north edge).
export function cellAt(cost, x, y) {
  const [ox, oy] = origin(cost)
  const col = Math.floor((x - ox) / cost.cellM)
  const row = cost.height - 1 - Math.floor((y - oy) / cost.cellM)
  if (!(col >= 0 && row >= 0 && col < cost.width && row < cost.height)) return null
  return { row, col, i: row * cost.width + col }
}

// Centre of cell i in metres.
export function centreAt(cost, i) {
  const [ox, oy] = origin(cost)
  const row = Math.floor(i / cost.width)
  const col = i - row * cost.width
  return [ox + (col + 0.5) * cost.cellM, oy + (cost.height - row - 0.5) * cost.cellM]
}

// Planning rate per cell for weight w, float64, evaluated exactly as section 15.2 writes it.
function planningRate(cost, w) {
  const { timeRate, riskRate } = cost
  const p = new Float64Array(timeRate.length)
  for (let i = 0; i < p.length; i++) p[i] = timeRate[i] * (1 + w * riskRate[i])
  return p
}

const CACHE_MAX = 24

// Dijkstra from one cell or a list of cells (cost 0 at each) with weight w, over the whole grid.
// Returns { g: Float64Array of cumulative planning cost (Infinity where unreached), from: Int32Array
// predecessor (-1 at a source or unreached), w, sources }. Cached on cost.searches when it exists.
export function searchFrom(cost, src, w = 0) {
  const sources = (Array.isArray(src) ? src : [src]).filter((s) => s != null)
  const key = `${sources.join(',')}|${w}`
  const hit = cost.searches?.get(key)
  if (hit) return hit
  const { width, height, cellM, blocked } = cost
  const n = width * height
  const p = planningRate(cost, w)
  const g = new Float64Array(n).fill(Infinity)
  const from = new Int32Array(n).fill(-1)
  const done = new Uint8Array(n)
  const L = [cellM, Math.sqrt(cellM * cellM + cellM * cellM)]
  const heap = new Heap()
  for (const s of sources) {
    if (blocked[s] || g[s] === 0) continue
    g[s] = 0
    heap.push(0, s)
  }
  while (heap.size) {
    const i = heap.pop()
    if (done[i]) continue
    done[i] = 1
    const r = Math.floor(i / width)
    const c = i - r * width
    const gi = g[i]
    const pi = p[i]
    for (let k = 0; k < 8; k++) {
      const rr = r + NEIGH[k][0]
      const cc = c + NEIGH[k][1]
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (blocked[j] || done[j]) continue
      const step = (L[NEIGH[k][2]] * (pi + p[j])) / 2
      const ng = gi + step
      if (ng < g[j]) {
        g[j] = ng
        from[j] = i
        heap.push(ng, j)
      }
    }
  }
  const out = { g, from, w, sources }
  if (cost.searches) {
    if (cost.searches.size >= CACHE_MAX) cost.searches.delete(cost.searches.keys().next().value)
    cost.searches.set(key, out)
  }
  return out
}

// The path from the search's source to dest (source first), or null when dest was not reached.
export function pathTo(search, dest) {
  if (dest == null || !Number.isFinite(search.g[dest])) return null
  const cells = [dest]
  while (search.from[cells[cells.length - 1]] !== -1) cells.push(search.from[cells[cells.length - 1]])
  return cells.reverse()
}

// Distance, physical walking time and risk minutes along a path of cells, in path order (section 15.3).
export function totals(cost, cells) {
  const { width, cellM, timeRate, riskRate } = cost
  const diag = cellM * Math.SQRT2
  let distance = 0
  let walk = 0
  let risk = 0
  for (let k = 1; k < cells.length; k++) {
    const a = cells[k - 1]
    const b = cells[k]
    const step = Math.floor(a / width) !== Math.floor(b / width) && a % width !== b % width ? diag : cellM
    const ta = timeRate[a]
    const tb = timeRate[b]
    distance += step
    walk += (step * (ta + tb)) / 2
    risk += (step * (ta * riskRate[a] + tb * riskRate[b])) / 2
  }
  return { distance_m: distance, walk_min: walk, risk_min: risk }
}

// Text for a reason code: mask codes 1-6 from the manifest, plus the two search results.
export function reasonText(cost, reason) {
  if (reason === 'outside') return 'outside the map'
  if (reason === 'landing_blocked') return 'the start cannot be walked on'
  if (reason === 'escape_unavailable') return "the start is inside a red zone, and routing's export has no escape rate (escape_time_rate) to walk out of it yet"
  if (reason === 'start_too_steep') return `Too steep to walk out of here: over ${cost.escape?.max_slope_deg ?? '?'}°`
  if (reason === 'no_exit') return 'no way out of the red zone around the start leads to the destination through the side quests'
  return cost.maskCodes?.find((m) => m.code === reason)?.text ?? `blocked (code ${reason})`
}

// One-way route from cell `from` to cell `to` with weight w, as export_landing.route gives it.
// budget: { ingress_min, stop_min, usable_min } (the manifest's budget by default).
// Returns { reachable, reason, reason_text, cells, geometry, distance_m, walk_min, risk_min,
// needed_min, over_budget } or, with no path, { reachable: false, reason, reason_text }.
export function route(cost, from, to, w, budget = cost.budget) {
  const fail = (reason) => ({ reachable: false, reason, reason_text: reasonText(cost, reason), w })
  if (from == null || to == null) return fail('outside')
  if (cost.blocked[from]) return fail('landing_blocked')
  if (cost.mask ? cost.mask[to] !== 0 : cost.blocked[to]) return fail(cost.mask ? cost.mask[to] : 1)
  const cells = pathTo(searchFrom(cost, from, w), to)
  if (!cells) return fail(6)
  const t = totals(cost, cells)
  const ingress = budget?.ingress_min ?? 0
  const stop = budget?.stop_min ?? 0
  const needed = t.walk_min + ingress + stop
  return {
    reachable: true,
    reason: 0,
    reason_text: null,
    w,
    cells,
    geometry: { type: 'LineString', coordinates: cells.map((i) => centreAt(cost, i)) },
    ...t,
    needed_min: needed,
    over_budget: budget?.usable_min != null ? needed > budget.usable_min : false,
  }
}

// Walking minutes (w = 0) or planning cost (w > 0) from src (a cell or a list of cells) to every cell.
// Step costs are the same in both directions, so this is also the cost from every cell back to src.
export function timeField(cost, src, w = 0) {
  return searchFrom(cost, src, w).g
}

// The nearest walkable cell to (x, y), searching out to maxM metres. Returns { i, movedM } or null.
// Only used to place mineral-area pins and order side quests; a route never snaps a point.
export function snapToFree(cost, x, y, maxM = 100) {
  const { width, height, cellM, blocked } = cost
  const home = cellAt(cost, x, y)
  if (!home) return null
  if (!blocked[home.i]) return { i: home.i, movedM: 0 }
  const rc = Math.ceil(maxM / cellM)
  let best = null
  for (let dr = -rc; dr <= rc; dr++) {
    for (let dc = -rc; dc <= rc; dc++) {
      const r = home.row + dr
      const c = home.col + dc
      if (r < 0 || c < 0 || r >= height || c >= width) continue
      const i = r * width + c
      if (blocked[i]) continue
      const [px, py] = centreAt(cost, i)
      const d = Math.hypot(px - x, py - y)
      if (d <= maxM && (!best || d < best.movedM)) best = { i, movedM: d }
    }
  }
  return best
}

// Numbers for a path of cells: the section 15.3 totals, plus slope, climb and ground class from the
// terrain grids (when the cost has them) and a sample per cell for the charts.
export function measurePath(cost, cells) {
  const { dem, slope, hazard, timeRate } = cost
  const { distance_m, walk_min, risk_min } = totals(cost, cells)
  const diag = cost.cellM * Math.SQRT2
  let d = 0
  let t = 0
  let ascent = 0
  let descent = 0
  let maxSlope = 0
  const byClass = [0, 0, 0]
  const track = []
  for (let k = 0; k < cells.length; k++) {
    const i = cells[k]
    const [x, y] = centreAt(cost, i)
    if (k > 0) {
      const j = cells[k - 1]
      const step = Math.floor(i / cost.width) !== Math.floor(j / cost.width) && i % cost.width !== j % cost.width ? diag : cost.cellM
      d += step
      t += (step * (timeRate[i] + timeRate[j])) / 2
      if (dem) {
        const dz = dem[i] - dem[j]
        if (dz > 0) ascent += dz
        else descent -= dz
      }
      if (hazard) byClass[hazard[i]] += step
    }
    const s = slope ? slope[i] : NaN
    if (Number.isFinite(s)) maxSlope = Math.max(maxSlope, s)
    track.push({ i, d, x, y, z: dem ? dem[i] : NaN, slope: s, hazard: hazard ? hazard[i] : 0, t })
  }
  return { distance_m, walk_min, risk_min, ascent_m: ascent, descent_m: descent, max_slope_deg: maxSlope, metres_by_class: byClass, track }
}

// One leg from point A to point B ({x, y} metres) with weight w. A blocked or unreachable point is
// never moved: the leg fails with the reason code and its text.
export function planLeg(cost, A, B, w) {
  const a = cellAt(cost, A.x, A.y)
  const b = cellAt(cost, B.x, B.y)
  const r = route(cost, a?.i, b?.i, w, null)
  if (!r.reachable) return { ok: false, reason: r.reason, reason_text: r.reason_text, end: r.reason === 'landing_blocked' ? 'start' : 'end' }
  return { ok: true, cells: r.cells, points: r.geometry.coordinates, ...measurePath(cost, r.cells) }
}
