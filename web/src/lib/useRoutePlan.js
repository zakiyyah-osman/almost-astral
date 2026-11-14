// The route-planning workflow both modes share (Team outing and My mission): one start (the landing in
// My mission, any walkable point in Team outing), side quests, a destination, the three profiles on
// routing's cost surface, minutes back to the start, the HUD plan and the timeline. The pure part is
// planRoutes (lib/routePlan.js); this hook only memoizes it for the active mode.
// Team outing before the user picks a start shows routing's plan.json demo route (lib/teamOuting.js).
import { useMemo } from 'react'
import { PROFILES } from './pathfind.js'
import { hudFor, planRoutes } from './routePlan.js'
import { waypointsFor } from './outing.js'
import { outingResults, outingWaypoints } from './teamOuting.js'
import { buildTimeline } from '../hud/sim.js'

// trip: { start, quests, dest, profile }. demo: { plan, routes, waypoints } (Team outing's default), or null.
// escape: true in Team outing, where a start inside a red zone walks out of it first (lib/escape.js).
export function useRoutePlan({ cost, params, trip, demo, doseFor, legCache, escape = false }) {
  const isDemo = !!demo && !trip.start
  // Home, for minutes back and the storm return: the trip's start, or plan.json start for the demo.
  const demoStart = demo?.plan?.start?.xy_m
  const home = trip.start ?? (isDemo && demoStart ? { x: demoStart[0], y: demoStart[1] } : null)
  const core = useMemo(
    () => (cost && params ? planRoutes(cost, params, isDemo ? { start: null, quests: [], dest: null } : trip, { home, doseFor, cache: legCache, escape }) : null),
    [cost, params, isDemo, trip.start, trip.quests, trip.dest, home?.x, home?.y, doseFor, legCache, escape], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const ingress = params?.ingress_min ?? 0
  const { back, stormField, shelterCells } = core ?? {}

  // Team outing's default: routing's files, sampled on the same grids.
  const demoResults = useMemo(() => (isDemo && cost ? outingResults(demo.plan, demo.routes, cost, back, ingress) : null), [isDemo, cost, demo, back, ingress])
  const results = isDemo ? demoResults : core?.results ?? null
  const profile = trip.profile ?? 'balanced'
  const active = results?.[profile]
  const ok = !!active?.ok
  const status = isDemo ? 'demo' : !core?.points ? 'incomplete' : ok ? 'ok' : 'failed'
  const altRoutes = useMemo(() => (results ? PROFILES.filter((p) => p.id !== profile && results[p.id]?.ok).map((p) => results[p.id].route) : null), [results, profile])

  const track = useMemo(() => (ok && back ? active.track.map((p) => ({ ...p, back: back[p.i] + ingress })) : null), [ok, active, back, ingress])
  const furthest = track ? track.reduce((a, b) => (b.back > a.back ? b : a)) : null

  const waypoints = useMemo(
    () => (isDemo ? outingWaypoints(demo.plan, demo.waypoints) : core?.points ? waypointsFor(core.waypointPoints ?? core.points) : null),
    [isDemo, demo, core],
  )
  // What the Plan section, the charts and the mission card read: the plan and route of the picked mode.
  const plan = isDemo ? demo.plan : ok ? active.plan : null
  const route = ok ? active.route : null
  // The HUD walks the picked route, with its track and storm return from the route's own cells (hudFor).
  const hud = useMemo(() => hudFor({ isDemo, demo, active, cost, back, stormField, ingress, waypoints }), [isDemo, demo, active, cost, back, stormField, ingress, waypoints])
  const arrivals = useMemo(() => {
    if (!plan || !waypoints) return {}
    const tl = buildTimeline(plan, waypoints, isDemo ? demo.routes?.balanced : route) // plan.json legs belong to the Balanced file
    return Object.fromEntries((tl?.segments ?? []).filter((s) => s.type === 'walk').map((s) => [s.to, s.t1]))
  }, [plan, waypoints, isDemo, demo, route])

  return { inZone: !!core?.inZone, status, isDemo, points: core?.points ?? null, results, active, ok, profile, altRoutes, track, furthest, back, stormField, shelterCells: shelterCells ?? [], waypoints, plan, route, hud, arrivals }
}
