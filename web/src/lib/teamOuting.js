// The Team outing tab: routing's own plan, drawn as exported. Nothing is searched again here.
// plan.json (legs, checks, track, storm_replan: the Balanced route) and plan.json `profiles` with their
// files (route_fastest.geojson, route.geojson, route_safest.geojson). The walk starts at plan.json
// `start` (routing's demo start), never at a rover waypoint.
import { PROFILES, cellAt } from './pathfind.js'

const lineOf = (fc) => fc?.features?.find((f) => f.geometry?.type === 'LineString')?.geometry.coordinates ?? null

// Samples along a polyline every cellM metres, with the terrain under each (for the route charts).
// Returns [{ i, d, x, y, z, slope, hazard }], or [] when the line is missing or leaves the grid.
export function sampleLine(cost, coords) {
  if (!coords?.length) return []
  const out = []
  let d = 0
  const add = (x, y, dd) => {
    const c = cellAt(cost, x, y)
    if (!c) return
    out.push({ i: c.i, d: dd, x, y, z: cost.dem ? cost.dem[c.i] : NaN, slope: cost.slope ? cost.slope[c.i] : NaN, hazard: cost.hazard ? cost.hazard[c.i] : 0 })
  }
  add(coords[0][0], coords[0][1], 0)
  for (let k = 1; k < coords.length; k++) {
    const [x0, y0] = coords[k - 1]
    const [x1, y1] = coords[k]
    const len = Math.hypot(x1 - x0, y1 - y0)
    const n = Math.max(1, Math.ceil(len / cost.cellM))
    for (let j = 1; j <= n; j++) add(x0 + ((x1 - x0) * j) / n, y0 + ((y1 - y0) * j) / n, d + (len * j) / n)
    d += len
  }
  return out
}

// The waypoints the outing uses: plan.json's start as a 'start' feature, then the stops. A 'rover'
// waypoint (deprecated) is dropped.
export function outingWaypoints(plan, waypoints) {
  const st = plan?.start
  const stops = (waypoints?.features ?? []).filter((f) => f.properties.kind === 'stop')
  const start = st?.xy_m
    ? [{ type: 'Feature', properties: { id: st.id ?? 'start', name: st.name ?? 'Demo start', kind: 'start', why: st.source ?? '' }, geometry: { type: 'Point', coordinates: st.xy_m } }]
    : []
  return { type: 'FeatureCollection', features: [...start, ...stops] }
}

// The unverified-stops warning of plan.json, or null.
export const unverifiedWarning = (plan) => (plan?.warnings ?? []).find((w) => /unverified/i.test(w)) ?? null

// One result per profile, in the shape the cards and the Compare tab read. plan is a summary from
// plan.json `profiles` only (rows it does not give are NaN); route is the profile's own file.
// routes: { fastest, balanced, safest } GeoJSON. back: minutes back to the start per cell (timeField).
export function outingResults(plan, routes, cost, back, ingress = 0) {
  const out = {}
  for (const p of PROFILES) {
    const prof = plan?.profiles?.[p.id]
    const route = routes?.[p.id]
    if (!prof || !lineOf(route)) {
      out[p.id] = { ok: false, reason: 'missing', reason_text: `plan.json has no ${p.id} route file`, fromFile: true }
      continue
    }
    const track = cost ? sampleLine(cost, lineOf(route)) : []
    const backs = back ? track.map((q) => back[q.i]).filter(Number.isFinite) : []
    out[p.id] = {
      ok: true,
      fromFile: true,
      route,
      track,
      furthest: backs.length ? Math.max(...backs) + ingress : null,
      plan: {
        fromFile: true,
        legs: [{ distance_m: prof.distance_m }],
        totals: { walk_min: prof.walk_min, stop_min: plan.totals?.stop_min ?? NaN, ingress_min: plan.totals?.ingress_min ?? NaN, total_min: prof.total_min },
        risk_min: prof.risk_min,
        metres_careful: NaN,
        max_slope_deg: NaN,
        ascent_m: NaN,
        descent_m: NaN,
        radiation_dose_usv: p.id === 'balanced' ? plan.radiation_dose_usv : NaN,
        checks: [{ id: 'status', ok: prof.status === 'ok', message: `Routing's planner: ${prof.status}` }],
      },
    }
  }
  return out
}

// Height, slope and climb for the Plan section, from plan.json's legs (it has no route-wide totals).
export function planExtras(plan) {
  const legs = plan?.legs ?? []
  const num = (k) => legs.map((l) => l[k]).filter(Number.isFinite)
  const sum = (k) => (num(k).length ? Math.round(num(k).reduce((s, v) => s + v, 0)) : NaN)
  return { max_slope_deg: num('max_slope_deg').length ? Math.max(...num('max_slope_deg')) : NaN, ascent_m: sum('ascent_m'), descent_m: sum('descent_m') }
}
