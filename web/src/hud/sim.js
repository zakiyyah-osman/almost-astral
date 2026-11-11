// Maths for the helmet HUD and the "simulate EVA" demo. No React in here.
//
// The astronaut follows the planned route. Time comes from plan.json: each leg
// takes walk_min, then the crew samples at the stop. A solar storm can be
// triggered at any moment; the astronaut then takes the shorter way back to the
// rover along the planned route, which is already known to avoid the hazards.

// ASSUMPTIONS (not from NASA data). Replace with the limits in mission/brief.md.
export const START_LOCAL_HOUR = 9 // the EVA leaves the rover at 09:00 local
export const BATTERY_MIN_PER_EVA = 1.5 // battery lasts 1.5 x the EVA time limit

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
  let i = 1
  while (i < pts.length - 1 && cum[i] < dd) i++
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

export function buildTimeline(plan, waypoints, route) {
  if (!plan?.legs?.length || !waypoints) return null
  const byId = {}
  for (const f of waypoints.features) byId[f.properties.id] = f
  const name = (id) => byId[id]?.properties.name ?? id
  const roverId = waypoints.features.find((f) => f.properties.kind === 'rover')?.properties.id ?? ROVER_ID

  // The path: the real route if there is one, otherwise straight lines between the stops.
  let pts = route?.features?.[0]?.geometry?.coordinates
  if (!pts || pts.length < 2) {
    const ids = [plan.legs[0].from, ...plan.legs.map((l) => l.to)]
    pts = ids.filter((id) => byId[id]).map((id) => byId[id].geometry.coordinates)
  }
  if (pts.length < 2) return null
  const cum = pathLength(pts)
  const routeLen = cum[cum.length - 1]

  const legTotal = plan.legs.reduce((s, l) => s + l.distance_m, 0) || 1
  const nStops = plan.legs.filter((l) => l.to !== roverId).length || 1
  const stopMin = plan.totals?.stop_min ?? 0

  const segments = []
  let t = 0
  let d = 0
  for (const leg of plan.legs) {
    const dEnd = d + (leg.distance_m / legTotal) * routeLen
    segments.push({ type: 'walk', t0: t, t1: t + leg.walk_min, d0: d, d1: dEnd, to: leg.to, toName: name(leg.to) })
    t += leg.walk_min
    d = dEnd
    if (leg.to !== roverId) {
      const dwell = leg.stop_min ?? stopMin / nStops
      segments.push({ type: 'stop', t0: t, t1: t + dwell, d0: d, d1: d, to: leg.to, toName: name(leg.to) })
      t += dwell
    }
  }

  const walkMin = plan.legs.reduce((s, l) => s + l.walk_min, 0) || 1
  return { pts, cum, routeLen, segments, totalMin: t, speed: routeLen / walkMin, name, roverId, roverName: name(roverId) }
}

// Everything the HUD shows at time t (minutes since the EVA began).
// storm is null, or { t, d } for the minute the storm hit and how far along the route the astronaut was.
export function stateAt(tl, t, storm) {
  if (storm && t >= storm.t) {
    // Shorter way home: back the way we came, or on along the route to the rover.
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
    shelterMin: Math.min(d, tl.routeLen - d) / tl.speed,
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

// ---- radiation -------------------------------------------------------------

export function parseRadiation(text) {
  const lines = text.trim().split(/\r?\n/)
  const head = lines[0].split(',')
  return lines.slice(1).map((line) => {
    const cells = line.split(',')
    return Object.fromEntries(head.map((h, i) => [h, Number(cells[i])]))
  })
}

export function radiationModel(rows) {
  if (!rows?.length) return null
  const sol = rows[0].sol
  const byHour = {}
  for (const r of rows) if (r.sol === sol) byHour[r.local_hour] = r.dose_rate_usv_h
  const rates = Object.values(byHour).sort((a, b) => a - b)
  return {
    sol,
    baseline: rates[Math.floor(rates.length / 2)],
    stormRate: rates[rates.length - 1], // the strongest hour in the data
    rateAt: (hour) => byHour[Math.floor(hour) % 24] ?? rates[0],
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
  for (let m = 0; m < t; m++) sum += doseRate(model, m + 0.5, storm) / 60
  return sum + (doseRate(model, t, storm) / 60) * (t - Math.floor(t))
}

// ---- display helpers -------------------------------------------------------

const CARDINALS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
export const cardinal = (deg) => CARDINALS[Math.round(deg / 45) % 8]

export function clock(totalMin) {
  const m = Math.floor(totalMin)
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

export function localClock(t) {
  return clock(START_LOCAL_HOUR * 60 + t)
}
