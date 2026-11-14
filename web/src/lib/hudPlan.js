// Turns the live route (the one picked in Planning: team outing or my mission, any mode) into the
// plan.json extras the HUD reads (CONTRACT.md): `track` (height, slope, ground class and minutes back
// to shelter along the route) and `storm_replan` (the fastest way home from points along the route).
// Everything comes from the HiRISE terrain grid and the walking model, the same as the planner.
import { centreOf } from './terrain.js'

const NEIGH = [
  [-1, 0, 1], [1, 0, 1], [0, -1, 1], [0, 1, 1],
  [-1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [1, 1, Math.SQRT2],
]
const r1 = (v) => Math.round(v * 10) / 10

// The way home from cell i, following a shortest-path field (minutes to the nearest shelter) to 0.
// field comes from timeField(cost, shelters, w); pass the same w here. Each step goes to the neighbour j
// that minimises field[j] + the cost of stepping to it. That is exactly the step the field was built from,
// so the walked path costs what the field says. (Just stepping to the lowest neighbour is not enough on
// an 8-direction grid: it ignores how far each step is and ends up on a slower path.)
// walk_min is the real walking time along the path, without the risk weight.
export function pathHome(cost, field, i, w = 0) {
  const { width, height, cellM, blocked, timeRate, riskRate } = cost
  const rate = (k) => timeRate[k] * (1 + w * riskRate[k])
  const cells = [i]
  let cur = i
  for (let guard = 0; guard < width * height && field[cur] > 0; guard++) {
    const r = Math.floor(cur / width)
    const c = cur % width
    let best = -1
    let bestCost = Infinity
    for (const [dr, dc, f] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (blocked[j] || !Number.isFinite(field[j])) continue
      const through = field[j] + ((rate(cur) + rate(j)) / 2) * f * cellM
      if (through < bestCost) {
        bestCost = through
        best = j
      }
    }
    if (best < 0) break // nowhere to go: should not happen on a finite field
    cells.push(best)
    cur = best
  }
  const path = cells.map((k) => centreOf(k, width, height, cellM))
  let m = 0
  let walk = 0
  for (let k = 1; k < cells.length; k++) {
    const len = Math.hypot(path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1])
    m += len
    walk += ((timeRate[cells[k]] + timeRate[cells[k - 1]]) / 2) * len
  }
  return { path, distance_m: m, walk_min: walk }
}

// plan: the live plan from planOuting. track: its samples ({ i, d, x, y, z, slope, hazard, t }).
// field: minutes from each cell to the nearest shelter. ingress: minutes to get inside.
// spacingM: how often along the route to store a storm return.
// storm: optional { field, w }: the storm return then follows timeField(cost, shelters, w) instead, so it stays
// off careful and no-go ground when that costs little time. return_min is always the real walking time.
export function hudPlan(plan, track, field, cost, ingress = 0, spacingM = 100, storm = null) {
  if (!plan || !track?.length || !field) return plan
  const rows = track
    .filter((p) => Number.isFinite(field[p.i]))
    .map((p) => ({
      distance_m: r1(p.d),
      x: r1(p.x),
      y: r1(p.y),
      elev_m: r1(p.z),
      slope_deg: r1(p.slope),
      hazard: p.hazard,
      shelter_min: r1(field[p.i] + ingress),
    }))

  const points = []
  let next = 0
  for (const p of track) {
    if (p.d < next || !Number.isFinite(field[p.i])) continue
    const home = pathHome(cost, storm?.field ?? field, p.i, storm?.field ? storm.w : 0)
    points.push({
      x: r1(p.x),
      y: r1(p.y),
      route_distance_m: r1(p.d),
      return_min: r1(home.walk_min + ingress),
      return_distance_m: Math.round(home.distance_m),
      path: home.path.map(([x, y]) => [r1(x), r1(y)]),
    })
    next = p.d + spacingM
  }

  return {
    ...plan,
    track: rows,
    storm_replan: { sample_spacing_m: spacingM, source: 'web route-finder (HiRISE terrain, walking model, risk-weighted)', points },
  }
}
