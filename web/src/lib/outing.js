// Turns planned legs into the same shapes as route.geojson and plan.json (CONTRACT.md), so every
// part of the app (charts, timeline, map labels, mission card) follows the route the crew picked.
import { planLeg } from './pathfind.js'

// points: [{ id, name, x, y, kind, stopMin? }] in visiting order. Minutes are spent at each point that
// is a science stop (kind 'stop'): its own stopMin, else opts.stopMin, else the planner's default;
// 0 for the start and any point of another kind. opts.cache: see cachedLeg.
export function planOuting(cost, points, w, params, opts = {}) {
  const legs = []
  const coords = []
  const tracks = []
  for (let k = 0; k < points.length - 1; k++) {
    const A = points[k]
    const B = points[k + 1]
    const leg = cachedLeg(cost, A, B, w, opts.cache)
    if (!leg.ok) return { ok: false, reason: leg.reason, reason_text: leg.reason_text, end: leg.end, leg: k, from: A, to: B }
    legs.push({ A, B, leg })
    const offset = tracks.length ? tracks[tracks.length - 1].d : 0
    for (let q = coords.length ? 1 : 0; q < leg.points.length; q++) {
      coords.push(leg.points[q])
      tracks.push({ ...leg.track[q], d: offset + leg.track[q].d, leg: k })
    }
  }
  return { ok: true, track: tracks, ...assemble(legs, coords, params, opts) }
}

// Legs are the slow part. A cache (a Map, one per terrain) lets the app re-plan a mission after a small
// change, or plan it without one side quest, and only search the legs that are new.
function cachedLeg(cost, A, B, w, cache) {
  if (!cache) return planLeg(cost, A, B, w)
  const key = `${Math.round(A.x)},${Math.round(A.y)}>${Math.round(B.x)},${Math.round(B.y)}|${w}`
  let leg = cache.get(key)
  if (!leg) {
    leg = planLeg(cost, A, B, w)
    cache.set(key, leg)
  }
  return leg
}

const r1 = (v) => Math.round(v * 10) / 10

function assemble(legs, coords, params, opts) {
  const stopMin = opts.stopMin ?? params.stop_min_default
  const planLegs = legs.map(({ A, B, leg }) => ({
    from: A.id,
    to: B.id,
    distance_m: Math.round(leg.distance_m),
    walk_min: r1(leg.walk_min),
    stop_min: B.kind === 'stop' ? (Number.isFinite(B.stopMin) ? B.stopMin : stopMin) : 0,
    risk_min: r1(leg.risk_min),
    ascent_m: Math.round(leg.ascent_m),
    descent_m: Math.round(leg.descent_m),
    max_slope_deg: r1(leg.max_slope_deg),
    metres_careful: Math.round(leg.metres_by_class[1]),
    metres_nogo: Math.round(leg.metres_by_class[2]),
  }))
  const walk = r1(planLegs.reduce((s, l) => s + l.walk_min, 0))
  const stops = planLegs.reduce((s, l) => s + l.stop_min, 0)
  const ingress = opts.ingress ? params.ingress_min : 0
  const total = r1(walk + stops + ingress)
  const usable = Math.round(params.eva_max_min * (1 - params.reserve_pct / 100))
  const dose = opts.doseFor ? Math.round(opts.doseFor(walk + stops)) : null
  // Needed time, unrounded, the way routing's one-way rule adds it (DESIGN section 15.5): walk + ingress + the
  // minutes on site. For one destination this equals export_landing.route's needed_min. Over budget is a
  // warning, not a failure.
  const walkExact = legs.reduce((s, { leg }) => s + leg.walk_min, 0)
  const neededMin = walkExact + ingress + stops
  const usableExact = params.usable_min ?? params.eva_max_min * (1 - params.reserve_pct / 100)
  const checks = []
  checks.push({ id: 'time', level: 'warn', ok: neededMin <= usableExact, value: total, limit: usable, message: total <= usable ? `Fits in the ${usable} min usable (${params.eva_max_min} min limit minus a ${params.reserve_pct}% reserve).` : `Over the ${usable} min usable time (${params.eva_max_min} min limit minus a ${params.reserve_pct}% reserve).` })
  if (dose != null) checks.push({ id: 'dose', ok: dose <= params.radiation_limit_usv, value: dose, limit: params.radiation_limit_usv, message: `Dose about ${dose} of ${params.radiation_limit_usv} µSv.` })
  const nogo = planLegs.reduce((s, l) => s + l.metres_nogo, 0)
  checks.push({ id: 'nogo', ok: nogo === 0, value: nogo, limit: 0, message: nogo === 0 ? 'Never enters no-go ground.' : `${nogo} m on no-go ground.` })

  const plan = {
    computed: true,
    start: { id: legs[0].A.id, name: legs[0].A.name, xy_m: [legs[0].A.x, legs[0].A.y] },
    needed_min: neededMin,
    over_budget: neededMin > usableExact,
    exact: {
      distance_m: legs.reduce((s, { leg }) => s + leg.distance_m, 0),
      walk_min: walkExact,
      risk_min: legs.reduce((s, { leg }) => s + leg.risk_min, 0),
    },
    crew: 2,
    legs: planLegs,
    totals: { walk_min: walk, stop_min: stops, ingress_min: ingress, total_min: total },
    budgets: { eva_max_min: params.eva_max_min, radiation_limit_usv: params.radiation_limit_usv, usable_min: usable, reserve_pct: params.reserve_pct },
    radiation_dose_usv: dose,
    status: checks.every((c) => c.ok) ? 'ok' : 'check',
    checks,
    risk_min: r1(planLegs.reduce((s, l) => s + l.risk_min, 0)),
    max_slope_deg: Math.max(...planLegs.map((l) => l.max_slope_deg)),
    ascent_m: planLegs.reduce((s, l) => s + l.ascent_m, 0),
    descent_m: planLegs.reduce((s, l) => s + l.descent_m, 0),
    metres_careful: planLegs.reduce((s, l) => s + l.metres_careful, 0),
    metres_nogo: nogo,
  }
  const route = {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: { source: 'web route-finder', profile: opts.profile ?? null }, geometry: { type: 'LineString', coordinates: coords } }],
  }
  return { plan, route }
}

// Waypoints for the timeline and the map labels: the outing's points as a GeoJSON FeatureCollection.
export function waypointsFor(points) {
  return {
    type: 'FeatureCollection',
    features: points
      .filter((p, i, arr) => arr.findIndex((q) => q.id === p.id) === i)
      .map((p) => ({ type: 'Feature', properties: { id: p.id, name: p.name, kind: p.kind, why: p.why ?? '', photo: p.photo ?? null, ...(p.extra ?? {}) }, geometry: { type: 'Point', coordinates: [Math.round(p.x), Math.round(p.y)] } })),
  }
}
