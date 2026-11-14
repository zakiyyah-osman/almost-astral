// The pure part of the shared route-planning workflow (both modes): from a trip { start, quests, dest }
// to the three profiles' routes on routing's cost surface, one way, with routing's budget rule
// (walk + ingress + each quest's minutes + the destination's stop, against usable_min; lib/outing.js),
// and the minutes back to the start from every cell. React-free, so the tests run it directly.
import { PROFILES, cellAt, reasonText, searchFrom, timeField } from './pathfind.js'
import { planOuting } from './outing.js'
import { missionPoints } from './mission.js'
import { planWithEscape, zoneOf } from './escape.js'
import { hudPlan } from './hudPlan.js'
import { demoHudPlan } from './teamOuting.js'

const homeSearch = (cost, params, cells) => ({
  shelterCells: cells,
  back: cells.length ? timeField(cost, cells) : null,
  // The storm return: as fast as Balanced allows, but off careful and no-go ground where that costs little.
  stormField: cells.length ? { search: searchFrom(cost, cells, params.w_balanced), w: params.w_balanced } : null,
})

// opts: { home: { x, y } (default trip.start), doseFor, cache, escape (Team outing: a start inside a red
// zone walks out of it first, lib/escape.js) }.
// Returns { points, waypointPoints, results, back, stormField, shelterCells, inZone }. points and results
// are null until the trip has a start and a destination; back is there as soon as there is a home.
// With an escape, "back to the start" means back to the red-zone exit: the crew cannot walk back in.
export function planRoutes(cost, params, trip, opts = {}) {
  const home = opts.home ?? trip.start
  const hc = home ? cellAt(cost, home.x, home.y) : null
  const inZone = !!(opts.escape && hc && zoneOf(cost, hc.i))
  const points = missionPoints(trip, params.stop_min_default)
  if (!points) return { points: null, waypointPoints: null, results: null, inZone, ...homeSearch(cost, params, hc && !inZone ? [hc.i] : []) }
  const ingress = params.ingress_min ?? 0
  const results = {}
  const planOpts = (p) => ({ ingress: true, doseFor: opts.doseFor, cache: opts.cache, profile: p.id, reasonText: (r) => reasonText(cost, r) })
  for (const p of PROFILES) {
    results[p.id] = inZone ? planWithEscape(cost, points, params[p.key], params, planOpts(p)) : planOuting(cost, points, params[p.key], params, planOpts(p))
  }
  // Home for minutes back and the storm return: the start, or the exit of the red zone it starts in.
  const exit = inZone ? (results.balanced?.exitPoint ?? PROFILES.map((p) => results[p.id].exitPoint).find(Boolean)) : null
  const hs = homeSearch(cost, params, inZone ? (exit ? [cellAt(cost, exit.x, exit.y).i] : []) : hc ? [hc.i] : [])
  for (const p of PROFILES) {
    const r = results[p.id]
    if (r.ok && hs.back) r.furthest = Math.max(...r.track.map((q) => hs.back[q.i]).filter(Number.isFinite)) + ingress
  }
  const waypointPoints = exit ? [points[0], exit, ...points.slice(1)] : points
  return { points, waypointPoints, results, inZone, ...hs }
}

// The HUD's plan, route and waypoints for the picked route: one route state for the map, the cards, the
// profile and every HUD metric. Track and storm return are always worked out from the route's own cells
// (lib/hudPlan.js); the demo route too (lib/teamOuting.js demoHudPlan), never plan.json's precomputed ones.
// No route (failed or not planned yet): null, so the HUD shows no metrics.
export function hudFor({ isDemo, demo, active, cost, back, stormField, ingress, waypoints }) {
  if (!active?.ok || !cost) return null
  if (isDemo) {
    const d = demoHudPlan(cost, demo.plan, active.route, waypoints)
    return d ? { plan: hudPlan(d.plan, d.track, back, cost, ingress, 100, stormField), route: active.route, waypoints } : null
  }
  return { plan: hudPlan(active.plan, active.track, back, cost, ingress, 100, stormField), route: active.route, waypoints }
}
