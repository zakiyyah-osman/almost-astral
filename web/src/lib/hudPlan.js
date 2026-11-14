// Turns the live route (the one picked in Planning: team outing or my mission, any mode) into the
// plan.json extras the HUD reads (CONTRACT.md): `track` (height, slope, ground class and minutes back
// to shelter along the route) and `storm_replan` (the fastest way home from points along the route).
// Everything comes from the HiRISE terrain grid and the walking model, the same as the planner.
import { centreOf } from './terrain.js'

const NEIGH = [
  [-1, 0], [1, 0], [0, -1], [0, 1],
  [-1, -1], [-1, 1], [1, -1], [1, 1],
]
const r1 = (v) => Math.round(v * 10) / 10

// The way home from cell i: step down the time field (minutes to the nearest shelter) until it reaches 0.
// timeField is a shortest-path field, so each step to the lowest neighbour follows a fastest path.
export function pathHome(cost, field, i) {
  const { width, height, cellM } = cost
  const cells = [i]
  let cur = i
  for (let guard = 0; guard < width * height && field[cur] > 0; guard++) {
    const r = Math.floor(cur / width)
    const c = cur % width
    let best = cur
    for (const [dr, dc] of NEIGH) {
      const rr = r + dr
      const cc = c + dc
      if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
      const j = rr * width + cc
      if (field[j] < field[best]) best = j
    }
    if (best === cur) break // nowhere lower: should not happen on a finite field
    cells.push(best)
    cur = best
  }
  const path = cells.map((k) => centreOf(k, width, height, cellM))
  let m = 0
  for (let k = 1; k < path.length; k++) m += Math.hypot(path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1])
  return { path, distance_m: m }
}

// plan: the live plan from planOuting. track: its samples ({ i, d, x, y, z, slope, hazard, t }).
// field: minutes from each cell to the nearest shelter. ingress: minutes to get inside.
// spacingM: how often along the route to store a storm return.
export function hudPlan(plan, track, field, cost, ingress = 0, spacingM = 100) {
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
    const home = pathHome(cost, field, p.i)
    points.push({
      x: r1(p.x),
      y: r1(p.y),
      route_distance_m: r1(p.d),
      return_min: r1(field[p.i] + ingress),
      return_distance_m: Math.round(home.distance_m),
      path: home.path.map(([x, y]) => [r1(x), r1(y)]),
    })
    next = p.d + spacingM
  }

  return {
    ...plan,
    track: rows,
    storm_replan: { sample_spacing_m: spacingM, source: 'web route-finder (HiRISE terrain, walking model)', points },
  }
}
