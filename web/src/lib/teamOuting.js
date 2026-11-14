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

// The demo route's plan for the HUD, worked out from the picked route file's own cells and routing's
// cost surface, not from plan.json's precomputed track or storm return. The line is cut at the stop
// nearest each visited waypoint (moving forwards only); each leg's distance, walking time and risk are
// summed along the 5 m samples (routing/docs/DESIGN.md section 15.3 on the sampled cells). Minutes on
// site, ingress and the budgets come from plan.json. Returns { plan, track } or null.
export function demoHudPlan(cost, plan, routeFc, waypoints) {
  const line = lineOf(routeFc)
  if (!cost || !plan?.legs?.length || !line) return null
  const track = sampleLine(cost, line)
  if (track.length < 2) return null
  const { timeRate, riskRate } = cost
  const rate = (i) => Math.max(0, timeRate[i])
  let t = 0
  let risk = 0
  track[0].t = 0
  track[0].risk = 0
  for (let k = 1; k < track.length; k++) {
    const a = track[k - 1].i
    const b = track[k].i
    const step = track[k].d - track[k - 1].d
    t += (step * (rate(a) + rate(b))) / 2
    risk += (step * (rate(a) * riskRate[a] + rate(b) * riskRate[b])) / 2
    track[k].t = t
    track[k].risk = risk
  }
  const byId = Object.fromEntries((waypoints?.features ?? []).map((f) => [f.properties.id, f.geometry.coordinates]))
  // Where each leg ends on the line: the nearest sample to its waypoint, after the previous cut; the last leg ends at the end.
  const cuts = [0]
  plan.legs.forEach((leg, k) => {
    if (k === plan.legs.length - 1) return cuts.push(track.length - 1)
    const p = byId[leg.to]
    let best = cuts[cuts.length - 1]
    if (p) {
      let bd = Infinity
      for (let q = best; q < track.length; q++) {
        const dd = Math.hypot(track[q].x - p[0], track[q].y - p[1])
        if (dd < bd) {
          bd = dd
          best = q
        }
      }
    }
    cuts.push(best)
  })
  const r1 = (v) => Math.round(v * 10) / 10
  const legs = plan.legs.map((leg, k) => {
    const a = track[cuts[k]]
    const b = track[cuts[k + 1]]
    const seg = track.slice(cuts[k], cuts[k + 1] + 1)
    let up = 0
    let down = 0
    for (let q = 1; q < seg.length; q++) {
      const dz = seg[q].z - seg[q - 1].z
      if (dz > 0) up += dz
      else down -= dz
    }
    return { from: leg.from, to: leg.to, distance_m: Math.round(b.d - a.d), walk_min: r1(b.t - a.t), stop_min: leg.stop_min ?? 0, risk_min: r1(b.risk - a.risk), ascent_m: Math.round(up), descent_m: Math.round(down), max_slope_deg: r1(Math.max(...seg.map((q) => q.slope).filter(Number.isFinite))) }
  })
  const walk = r1(legs.reduce((s, l) => s + l.walk_min, 0))
  const stops = legs.reduce((s, l) => s + l.stop_min, 0)
  const ingress = plan.totals?.ingress_min ?? 0
  return {
    plan: { start: plan.start, legs, totals: { walk_min: walk, stop_min: stops, ingress_min: ingress, total_min: r1(walk + stops + ingress) }, budgets: plan.budgets, radiation_dose_usv: plan.radiation_dose_usv, from_route_cells: true },
    track,
  }
}
