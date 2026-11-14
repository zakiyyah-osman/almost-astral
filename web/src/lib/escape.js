// Walking out of a red zone (Team outing only), when the chosen start lies inside one.
//
// A red zone is a connected (8 neighbours) region of blocked cells whose mask code is in zone_codes:
// red hazard (2), slope over the limit (3), the cliff buffer (4) and sealed gaps (5); never no data (1)
// or outside the grid. Team choice (Tushaar); routing's manifest can override it with escape.zone_codes.
//
// The rates inside the zone are NOT invented here: they come from routing's export, escape_time_rate.f64
// and escape_risk_rate.f64 (routing/docs/DESIGN.md section 17; -1 where a zone cell is steeper than
// escape.max_slope_deg, which is never entered). Without them there is no escape. golden_escape_cases.json
// is the test (escape.test.js).
//
// Phase 1: Dijkstra inside the zone C only (routing/docs/DESIGN.md section 15.2 step rule, escape rates
//          in C), from the start to every exit: a passable cell next to C, entered in one step and never
//          expanded further.
// Exit:    the shortest escape walk time among exits from which the destination, through the side quests,
//          can be reached on passable ground; exact ties go to the lowest total planning cost.
// Phase 2: the normal search (lib/outing.js) from that exit; it never enters any blocked cell, C included.
import { Heap, centreAt, cellAt, measurePath, searchFrom } from './pathfind.js'
import { planOuting } from './outing.js'

export const DEFAULT_ZONE_CODES = [2, 3, 4, 5]
export const zoneCodes = (cost) => cost.escape?.zone_codes ?? DEFAULT_ZONE_CODES
export const escapeAvailable = (cost) => !!(cost.escapeTimeRate && cost.escapeRiskRate)

const NEIGH = [
  [-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0],
  [-1, -1, 1], [-1, 1, 1], [1, -1, 1], [1, 1, 1],
]

// True when cell i is blocked with a red-zone code.
export const inZoneCode = (cost, i) => cost.mask[i] !== 0 && zoneCodes(cost).includes(cost.mask[i])

// The red zone holding cell start: { start, cells, has: Uint8Array }, or null if start is not in one.
export function zoneOf(cost, start) {
  if (start == null || !inZoneCode(cost, start)) return null
  const { width, height } = cost
  const has = new Uint8Array(width * height)
  const cells = [start]
  has[start] = 1
  for (let k = 0; k < cells.length; k++) {
    const r = Math.floor(cells[k] / width)
    const c = cells[k] - r * width
    for (const [dr, dc] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (!has[j] && inZoneCode(cost, j)) {
        has[j] = 1
        cells.push(j)
      }
    }
  }
  return { start, cells, has }
}

// Connected regions of passable cells (8 neighbours), cached on the cost: Int32Array of labels, -1 if blocked.
export function passableRegions(cost) {
  if (cost._regions) return cost._regions
  const { width, height, blocked } = cost
  const n = width * height
  const lab = new Int32Array(n).fill(-1)
  let next = 0
  for (let i = 0; i < n; i++) {
    if (blocked[i] || lab[i] >= 0) continue
    const stack = [i]
    lab[i] = next
    while (stack.length) {
      const j = stack.pop()
      const r = Math.floor(j / width)
      const c = j - r * width
      for (const [dr, dc] of NEIGH) {
        const rr = r + dr
        const cc = c + dc
        if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
        const q = rr * width + cc
        if (!blocked[q] && lab[q] < 0) {
          lab[q] = next
          stack.push(q)
        }
      }
    }
    next++
  }
  cost._regions = lab
  return lab
}

// The rates along an escape: routing's escape rates in the zone, the normal rates elsewhere.
function escapeRates(cost, zone) {
  const timeRate = Float64Array.from(cost.timeRate)
  const riskRate = Float64Array.from(cost.riskRate)
  for (const i of zone.cells) {
    timeRate[i] = cost.escapeTimeRate[i]
    riskRate[i] = cost.escapeRiskRate[i]
  }
  return { timeRate, riskRate }
}

// Phase 1 for weight w: { g, from, exits: [cell] } inside the zone, exits included (not expanded).
export function escapeSearch(cost, zone, rates, w) {
  const { width, height, cellM, blocked } = cost
  const n = width * height
  const p = (i) => rates.timeRate[i] * (1 + w * rates.riskRate[i])
  const g = new Float64Array(n).fill(Infinity)
  const from = new Int32Array(n).fill(-1)
  const done = new Uint8Array(n)
  const L = [cellM, Math.sqrt(cellM * cellM + cellM * cellM)]
  const exits = []
  const heap = new Heap()
  g[zone.start] = 0
  heap.push(0, zone.start)
  while (heap.size) {
    const i = heap.pop()
    if (done[i]) continue
    done[i] = 1
    if (!zone.has[i]) {
      exits.push(i) // a passable cell next to the zone: the escape ends here
      continue
    }
    const r = Math.floor(i / width)
    const c = i - r * width
    const pi = p(i)
    for (const [dr, dc, diag] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (done[j] || !(zone.has[j] || !blocked[j])) continue // stay in the zone, or step onto passable ground
      if (zone.has[j] && !(rates.timeRate[j] >= 0)) continue // steeper than escape.max_slope_deg
      const ng = g[i] + (L[diag] * (pi + p(j))) / 2
      if (ng < g[j]) {
        g[j] = ng
        from[j] = i
        heap.push(ng, j)
      }
    }
  }
  return { g, from, exits }
}

const chain = (search, cell) => {
  const cells = [cell]
  while (search.from[cells[cells.length - 1]] !== -1) cells.push(search.from[cells[cells.length - 1]])
  return cells.reverse()
}

const fail = (reason, text, from, to) => ({ ok: false, reason, reason_text: text, from, to, leg: 0 })

// Plans points (points[0] = the start inside a red zone, then quests, then the destination) for weight w:
// the escape, then the normal route. Returns planOuting's shape with plan.escape, or a failure.
// reasonText: (code) => text, for blocked quests or destination.
export function planWithEscape(cost, points, w, params, opts = {}) {
  const [A, ...rest] = points
  const startCell = cellAt(cost, A.x, A.y)?.i
  const zone = zoneOf(cost, startCell)
  if (!zone) return planOuting(cost, points, w, params, opts)
  if (!escapeAvailable(cost)) return fail('escape_unavailable', opts.reasonText?.('escape_unavailable'), A, rest[0])
  if (!(cost.escapeTimeRate[startCell] >= 0)) return { ...fail('start_too_steep', opts.reasonText?.('start_too_steep'), A, rest[0]), status: 'no_exit' }
  // Every quest and the destination must be passable, in one region: the exits must reach that region.
  const regions = passableRegions(cost)
  const cells = rest.map((p) => cellAt(cost, p.x, p.y)?.i)
  for (let k = 0; k < rest.length; k++) {
    if (cells[k] == null) return fail('outside', opts.reasonText?.('outside'), A, rest[k])
    if (cost.mask[cells[k]]) return fail(cost.mask[cells[k]], opts.reasonText?.(cost.mask[cells[k]]), k ? rest[k - 1] : A, rest[k])
  }
  const target = regions[cells[0]]
  if (cells.some((c) => regions[c] !== target)) return { ...fail('no_exit', opts.reasonText?.('no_exit'), A, rest[cells.findIndex((c) => regions[c] !== target)]), status: 'no_exit' }

  const rates = escapeRates(cost, zone)
  const walk = escapeSearch(cost, zone, rates, 0) // escape walk time decides
  const valid = walk.exits.filter((e) => regions[e] === target)
  if (!valid.length) return { ...fail('no_exit', opts.reasonText?.('no_exit'), A, rest[rest.length - 1]), status: 'no_exit' }
  const best = Math.min(...valid.map((e) => walk.g[e]))
  let tied = valid.filter((e) => walk.g[e] === best)
  if (tied.length > 1) {
    // Exact ties: the lowest total planning cost for this weight (escape + every leg after it).
    const plan = escapeSearch(cost, zone, rates, w)
    const total = (e) => {
      let s = plan.g[e]
      let from = e
      for (const c of cells) {
        s += searchFrom(cost, from, w).g[c]
        from = c
      }
      return s
    }
    tied = [tied.reduce((a, b) => (total(b) < total(a) ? b : a))]
  }
  const exit = tied[0]
  const escCells = chain(walk, exit)
  const [ex, ey] = centreAt(cost, exit)
  const B = { id: 'exit', kind: 'exit', name: 'Red-zone exit', x: ex, y: ey }
  const leg = { ok: true, cells: escCells, points: escCells.map((i) => centreAt(cost, i)), ...measurePath({ ...cost, ...rates }, escCells) }
  const r = planOuting(cost, [B, ...rest], w, params, { ...opts, escape: { A, B, leg } })
  return r.ok ? { ...r, exitPoint: B } : r
}
