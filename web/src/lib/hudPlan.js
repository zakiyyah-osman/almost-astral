// Turns the live route (the one picked in Planning: team outing or my mission, any mode) into the
// plan.json extras the HUD reads (CONTRACT.md): `track` (height, slope, ground class and minutes back
// to shelter along the route) and `storm_replan` (the fastest way home from points along the route).
// Heights and slopes come from the HiRISE terrain grid; times and paths from routing's cost surface.
import { centreAt, totals } from './pathfind.js'

const r1 = (v) => Math.round(v * 10) / 10

// The way home from cell i: the predecessor chain of a search from the shelters (searchFrom), which
// is the least-cost path from the shelter to i. Step costs are the same in both directions, so walked
// backwards it is also the least-cost way from i home. walk_min is the physical walking time along it
// (routing/docs/DESIGN.md section 15.3), without the risk weight.
export function pathHome(cost, search, i) {
  const cells = [i]
  while (search.from[cells[cells.length - 1]] !== -1) cells.push(search.from[cells[cells.length - 1]])
  const t = totals(cost, cells)
  return { cells, path: cells.map((k) => centreAt(cost, k)), distance_m: t.distance_m, walk_min: t.walk_min }
}

// plan: the live plan from planOuting. track: its samples ({ i, d, x, y, z, slope, hazard, t }).
// field: minutes from each cell to the nearest shelter (timeField). ingress: minutes to get inside.
// spacingM: how often along the route to store a storm return.
// storm: { search, w }: a searchFrom(cost, shelters, w) whose paths the storm return follows; with w > 0 it
// stays off careful and no-go ground when that costs little time. Without it the plan is returned as it
// is. return_min is always the real walking time.
export function hudPlan(plan, track, field, cost, ingress = 0, spacingM = 100, storm = null) {
  if (!plan || !track?.length || !field || !storm?.search) return plan
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
    const home = pathHome(cost, storm.search, p.i)
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
    storm_replan: { sample_spacing_m: spacingM, source: `web route-finder on routing's cost surface (data/out/landing), w = ${storm.w}`, points },
  }
}
