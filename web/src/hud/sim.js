// Maths for the helmet HUD and the "simulate EVA" demo. No React in here.
//
// The astronaut follows the planned route. Time comes from plan.json: each leg
// takes walk_min, then the crew samples at the stop. A solar storm can be
// triggered at any moment; the astronaut then heads back to the landing: along the
// storm return path in plan.json when the planner gave one, otherwise the shorter
// way back along the planned route, which is already known to avoid the hazards.
//
// Written to cope with real data: a route with hundreds of points, a route that
// passes near (not exactly through) the stops, tables with several sols, missing
// hours and bad rows.

// ASSUMPTIONS (not from NASA data). Replace with the limits in mission/brief.md.
export const START_LOCAL_HOUR = 9 // the EVA leaves the start at 09:00 local
export const BATTERY_MIN_PER_EVA = 1.5 // battery lasts 1.5 x the EVA time limit
export const DUST_WARN_TAU = 1.5 // dust opacity above this triggers a dust alert

const ROVER_ID = 'rover'

function pathLength(pts) {
  const cum = [0]
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  }
  return cum
}

// Position and travel direction at distance d along the path. dir is +1 when
// walking the path forwards and -1 when walking it backwards.
function pointAt(pts, cum, d, dir) {
  const total = cum[cum.length - 1]
  const dd = Math.min(Math.max(d, 0), total)
  // binary search for the first vertex at or beyond dd
  let lo = 1
  let hi = pts.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (cum[mid] < dd) lo = mid + 1
    else hi = mid
  }
  const i = lo
  const [x0, y0] = pts[i - 1]
  const [x1, y1] = pts[i]
  const len = cum[i] - cum[i - 1] || 1
  const f = (dd - cum[i - 1]) / len
  const dx = (x1 - x0) * dir
  const dy = (y1 - y0) * dir
  // x is east, y is north, so a bearing measured clockwise from north is atan2(dx, dy)
  const heading = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360
  return { x: x0 + (x1 - x0) * f, y: y0 + (y1 - y0) * f, heading }
}

// Distance along the path of the point nearest to p, looking only from fromD onwards.
function projectForward(pts, cum, p, fromD) {
  let best = { d: fromD, dist: Infinity }
  for (let i = 1; i < pts.length; i++) {
    if (cum[i] < fromD) continue
    const [x0, y0] = pts[i - 1]
    const [x1, y1] = pts[i]
    const vx = x1 - x0
    const vy = y1 - y0
    const len2 = vx * vx + vy * vy || 1
    let u = ((p[0] - x0) * vx + (p[1] - y0) * vy) / len2
    u = Math.min(Math.max(u, 0), 1)
    const d = Math.max(cum[i - 1] + u * Math.sqrt(len2), fromD)
    const dist = Math.hypot(x0 + vx * u - p[0], y0 + vy * u - p[1])
    if (dist < best.dist - 1e-9) best = { d, dist }
  }
  return best
}

// The path as a list of [x, y]: the first LineString of the route, joined up if it is a MultiLineString.
function routePoints(route) {
  const g = route?.features?.find((f) => f.geometry?.type === 'LineString' || f.geometry?.type === 'MultiLineString')?.geometry
  if (!g) return null
  const pts = g.type === 'LineString' ? g.coordinates : g.coordinates.flat()
  const clean = pts.filter((c) => Number.isFinite(c?.[0]) && Number.isFinite(c?.[1]))
  return clean.length >= 2 ? clean : null
}

// ---- real route data from the route planner (plan.json: track and storm_replan) ----
// Both are optional. Without them the HUD falls back to straight distance over walking pace.

const isNum = (v) => Number.isFinite(v)
const isPoint = (p) => Array.isArray(p) && isNum(p[0]) && isNum(p[1])

// The planner's samples along the route: elevation, slope, ground class and minutes back to shelter.
function trackModel(rows) {
  if (!Array.isArray(rows)) return null
  const good = rows
    .filter((r) => isNum(r?.distance_m) && isNum(r.elev_m) && isNum(r.slope_deg) && isNum(r.shelter_min))
    .sort((a, b) => a.distance_m - b.distance_m)
  return good.length >= 2 ? good : null
}

// The planner's storm return from points along the route: the fastest way home and how long it takes.
function stormModel(replan) {
  if (!Array.isArray(replan?.points)) return null
  const good = replan.points
    .filter((p) => isNum(p?.route_distance_m) && isNum(p.return_min) && isNum(p.return_distance_m) && Array.isArray(p.path) && p.path.length >= 1 && p.path.every(isPoint))
    .sort((a, b) => a.route_distance_m - b.route_distance_m)
  return good.length ? good : null
}

// Elevation, slope, ground class (0 go, 1 careful, 2 no-go) and minutes back to shelter at distance d
// along the route, or null when the plan has no track.
export function trackAt(tl, d) {
  const tr = tl?.track
  if (!tr) return null
  const dd = Math.min(Math.max(d, tr[0].distance_m), tr[tr.length - 1].distance_m)
  let lo = 1
  let hi = tr.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (tr[mid].distance_m < dd) lo = mid + 1
    else hi = mid
  }
  const a = tr[lo - 1]
  const b = tr[lo]
  const span = b.distance_m - a.distance_m
  const f = span > 0 ? (dd - a.distance_m) / span : 0
  const mix = (k) => a[k] + (b[k] - a[k]) * f
  return { elev: mix('elev_m'), slope: mix('slope_deg'), shelter: mix('shelter_min'), hazard: Math.max(a.hazard ?? 0, b.hazard ?? 0) }
}

// A solar storm that starts at EVA minute t, when the crew is d metres along the route.
// If the plan has a storm return for this part of the route, the crew follows that path home at the
// planner's pace (its minutes include getting inside); otherwise stateAt turns round on the route.
export function startStorm(tl, t, d) {
  const storm = { t, d }
  if (!tl.stormPts) return storm
  let best = tl.stormPts[0]
  for (const p of tl.stormPts) if (Math.abs(p.route_distance_m - d) < Math.abs(best.route_distance_m - d)) best = p
  const here = pointAt(tl.pts, tl.cum, d, 1)
  const [px, py] = best.path[0]
  if (Math.hypot(here.x - px, here.y - py) > 150) return storm // the plan does not match this route
  const pts = [[here.x, here.y], ...best.path]
  const cum = pathLength(pts)
  const walkMin = best.return_min - tl.ingressMin
  const speed = best.return_distance_m > 0 && walkMin > 0.5 ? best.return_distance_m / walkMin : tl.speed
  return { ...storm, ret: { pts, cum, len: cum[cum.length - 1], speed, ingress: tl.ingressMin } }
}

export function buildTimeline(plan, waypoints, route) {
  if (!plan?.legs?.length || !waypoints?.features?.length) return null
  const byId = {}
  for (const f of waypoints.features) byId[f.properties.id] = f
  const name = (id) => byId[id]?.properties.name ?? (id === plan.start?.id ? plan.start.name : id)
  // Home is where the walk starts: plan.start (routing's demo start, or the landing of a custom mission),
  // else the first leg's start. A 'rover' waypoint is never used: there is no rover, only walking.
  // (The field keeps its old name, roverId, for the HUD and the charts.) The last leg ends the outing
  // (back home, or at a one-way destination), so it is never a sampling stop.
  const roverId = plan.start?.id ?? plan.legs[0].from ?? ROVER_ID
  const homeIds = new Set([roverId, plan.legs[0].from])
  // The walk out of a red zone (leg.escape, web/src/lib/escape.js) ends at its exit: not a sampling stop.
  const isStop = (leg, i) => i < plan.legs.length - 1 && !homeIds.has(leg.to) && !leg.escape

  // The path: the real route if there is one, otherwise straight lines between the stops.
  let pts = routePoints(route)
  if (!pts) {
    const ids = [plan.legs[0].from, ...plan.legs.map((l) => l.to)]
    pts = ids.filter((id) => byId[id]).map((id) => byId[id].geometry.coordinates)
  }
  if (pts.length < 2) return null
  const cum = pathLength(pts)
  const routeLen = cum[cum.length - 1]

  const nStops = plan.legs.filter(isStop).length || 1
  const stopMin = plan.totals?.stop_min ?? 0

  // Where each leg ends on the path: the nearest route point to the stop, moving forwards only.
  // The last leg ends at the end of the route (back at the start).
  const segments = []
  let t = 0
  let d = 0
  plan.legs.forEach((leg, i) => {
    const last = i === plan.legs.length - 1
    const target = byId[leg.to]?.geometry.coordinates
    const dEnd = last ? routeLen : target ? projectForward(pts, cum, target, d).d : d
    segments.push({ type: 'walk', t0: t, t1: t + leg.walk_min, d0: d, d1: dEnd, to: leg.to, toName: name(leg.to) })
    t += leg.walk_min
    d = dEnd
    if (isStop(leg, i)) {
      const dwell = leg.stop_min ?? stopMin / nStops
      segments.push({ type: 'stop', t0: t, t1: t + dwell, d0: d, d1: d, to: leg.to, toName: name(leg.to) })
      t += dwell
    }
  })

  const walkMin = plan.legs.reduce((s, l) => s + l.walk_min, 0) || 1
  // Use the planner's track only if it describes this route (about the same length).
  let track = trackModel(plan.track)
  if (track && Math.abs(track[track.length - 1].distance_m - routeLen) > routeLen * 0.05) track = null
  return {
    pts, cum, routeLen, segments, totalMin: t, speed: routeLen / walkMin, name, roverId, roverName: name(roverId),
    track,
    stormPts: track ? stormModel(plan.storm_replan) : null,
    ingressMin: plan.totals?.ingress_min ?? 0,
  }
}

// Everything the HUD shows at time t (minutes since the EVA began).
// storm is null, or { t, d } for the minute the storm hit and how far along the route the astronaut was.
export function stateAt(tl, t, storm) {
  if (storm?.ret && t >= storm.t) {
    // The planner's way home: it may leave the route when that is quicker.
    const r = storm.ret
    const moved = Math.min((t - storm.t) * r.speed, r.len)
    const left = r.len - moved
    return {
      phase: left <= 0 ? 'done' : 'return',
      d: storm.d,
      ...pointAt(r.pts, r.cum, moved, 1),
      nextId: tl.roverId,
      nextName: tl.roverName,
      nextDist: left,
      shelterMin: left <= 0 ? 0 : left / r.speed + r.ingress,
      pace: left <= 0 ? 0 : r.speed,
    }
  }
  if (storm && t >= storm.t) {
    // Shorter way home: back the way we came, or on along the route to the start.
    const back = storm.d <= tl.routeLen - storm.d
    const homeDist = back ? storm.d : tl.routeLen - storm.d
    const moved = Math.min((t - storm.t) * tl.speed, homeDist)
    const d = back ? storm.d - moved : storm.d + moved
    const left = homeDist - moved
    return {
      phase: left <= 0 ? 'done' : 'return',
      d,
      ...pointAt(tl.pts, tl.cum, d, back ? -1 : 1),
      nextId: tl.roverId,
      nextName: tl.roverName,
      nextDist: left,
      shelterMin: left / tl.speed,
      pace: left <= 0 ? 0 : tl.speed,
    }
  }

  const tt = Math.min(t, tl.totalMin)
  const i = Math.max(tl.segments.findIndex((s) => tt < s.t1), 0)
  const seg = tl.segments.find((s) => tt < s.t1) ?? tl.segments[tl.segments.length - 1]
  const f = seg.t1 > seg.t0 ? (tt - seg.t0) / (seg.t1 - seg.t0) : 1
  const d = seg.d0 + (seg.d1 - seg.d0) * f
  const done = t >= tl.totalMin
  // While sampling, "next" is where the crew walks after this stop.
  const target = seg.type === 'stop' ? tl.segments[i + 1] ?? seg : seg
  return {
    phase: done ? 'done' : seg.type,
    d,
    ...pointAt(tl.pts, tl.cum, d, 1),
    nextId: target.to,
    nextName: target.toName,
    nextDist: seg.type === 'stop' ? target.d1 - target.d0 : Math.max(seg.d1 - d, 0),
    // The planner's minutes back to shelter when it gave us a track, else distance over pace.
    shelterMin: done ? 0 : tl.track ? trackAt(tl, d).shelter : Math.min(d, tl.routeLen - d) / tl.speed,
    // Metres per minute on the ground right now: the leg's distance over its walking time (0 when stopped).
    pace: seg.type === 'walk' && !done ? (seg.d1 - seg.d0) / (seg.t1 - seg.t0 || 1) : 0,
  }
}

// Where the astronaut has been: a position every `step` minutes from 0 to t.
export function trailUntil(tl, t, storm, step = 2) {
  const out = []
  for (let m = 0; m < t; m += step) {
    const s = stateAt(tl, m, storm && storm.t <= m ? storm : null)
    out.push([s.x, s.y])
  }
  const last = stateAt(tl, t, storm)
  out.push([last.x, last.y])
  return out
}

// The stops in visiting order, each with the minutes it is sampled.
export function stopList(tl) {
  return tl.segments.filter((s) => s.type === 'stop')
}

// ---- tables (radiation, weather) -------------------------------------------

// Reads a CSV of numbers into rows. Blank lines and rows with a bad local_hour are skipped,
// and a cell that is not a number becomes NaN so callers can ignore it.
export function parseTable(text) {
  const lines = String(text ?? '').trim().split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) return []
  const head = lines[0].split(',').map((h) => h.trim())
  return lines
    .slice(1)
    .map((line) => {
      const cells = line.split(',')
      return Object.fromEntries(head.map((h, i) => [h, cells[i] === undefined || cells[i].trim() === '' ? NaN : Number(cells[i])]))
    })
    .filter((r) => Number.isFinite(r.local_hour))
}
export const parseRadiation = parseTable

// One sol's rows, sorted by hour. Uses the sol with the most rows (the fullest day).
function oneSol(rows, field) {
  const good = rows.filter((r) => Number.isFinite(r[field]) && Number.isFinite(r.sol))
  if (!good.length) return null
  const counts = {}
  for (const r of good) counts[r.sol] = (counts[r.sol] ?? 0) + 1
  const sol = Number(Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a - b)[0])
  return { sol, rows: good.filter((r) => r.sol === sol).sort((a, b) => a.local_hour - b.local_hour) }
}

// The latest row at or before this local hour, wrapping round midnight.
function rowAt(sorted, hour) {
  const h = ((hour % 24) + 24) % 24
  let pick = sorted[sorted.length - 1] // before the first row of the day: use the last one (yesterday evening)
  for (const r of sorted) {
    if (r.local_hour <= h) pick = r
    else break
  }
  return pick
}

export function radiationModel(rows) {
  const day = rows && oneSol(rows, 'dose_rate_usv_h')
  if (!day) return null
  const rates = day.rows.map((r) => r.dose_rate_usv_h).sort((a, b) => a - b)
  return {
    sol: day.sol,
    baseline: rates[Math.floor(rates.length / 2)],
    stormRate: rates[rates.length - 1], // the strongest hour in the data
    rateAt: (hour) => rowAt(day.rows, hour).dose_rate_usv_h,
  }
}

// Dose rate (µSv/h) at EVA minute t. After a storm hits, the astronaut is in the storm's rate.
export function doseRate(model, t, storm) {
  const hourRate = model.rateAt(START_LOCAL_HOUR + t / 60)
  return storm && t >= storm.t ? Math.max(hourRate, model.stormRate) : hourRate
}

// Total dose (µSv) from minute 0 to t, summed minute by minute.
export function doseTotal(model, t, storm) {
  let sum = 0
  for (let m = 0; m < Math.floor(t); m++) sum += doseRate(model, m + 0.5, storm) / 60
  return sum + (doseRate(model, t, storm) / 60) * (t - Math.floor(t))
}

// Weather: temperature (°C), pressure (Pa) and dust opacity for the same sol-day.
export function weatherModel(rows) {
  const day = rows && oneSol(rows, 'temp_c')
  if (!day) return null
  const at = (hour) => {
    const r = rowAt(day.rows, hour)
    return {
      temp: r.temp_c,
      pressure: Number.isFinite(r.pressure_pa) ? r.pressure_pa : null,
      dust: Number.isFinite(r.dust_tau) ? r.dust_tau : null,
    }
  }
  return { sol: day.sol, at }
}

// ---- display helpers -------------------------------------------------------

const CARDINALS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
export const cardinal = (deg) => CARDINALS[Math.round(deg / 45) % 8]

export function clock(totalMin) {
  const m = Math.floor(totalMin)
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

export function localClock(t) {
  return clock((START_LOCAL_HOUR * 60 + t) % (24 * 60))
}

// Real solar events from NASA DONKI (space_weather.csv). Text columns, so it has its own parser.
// Returns the events DONKI says reach Mars and the fastest of them, or null if there are none.
export function spaceWeatherModel(text) {
  const lines = String(text ?? '').trim().split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) return null
  const head = lines[0].split(',').map((h) => h.trim())
  const rows = lines.slice(1).map((line) => {
    const cells = line.split(',')
    return Object.fromEntries(head.map((h, i) => [h, (cells[i] ?? '').trim()]))
  })
  const hits = rows
    .filter((r) => r.mars_impact === 'True' && r.mars_arrival_utc)
    .map((r) => ({ ...r, kms: parseFloat(r.detail) || 0 }))
  if (!hits.length) return null
  const fastest = hits.reduce((a, b) => (b.kms > a.kms ? b : a))
  return { total: rows.length, hits: hits.length, fastest }
}
