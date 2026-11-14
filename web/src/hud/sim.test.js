// Tests for the HUD maths. Run with: npm test (from web/).
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  buildTimeline,
  doseTotal,
  localClock,
  parseTable,
  radiationModel,
  stateAt,
  startStorm,
  stopList,
  trackAt,
  trailUntil,
  weatherModel,
  spaceWeatherModel,
} from './sim.js'

// A fixed example outing (a copy of an earlier plan), so these tests do not change when the real plan in data/out does.
const out = (f) => JSON.parse(readFileSync(new URL(`./fixtures/${f}`, import.meta.url), 'utf8'))
const plan = out('plan.json')
const waypoints = out('waypoints.geojson')
const route = out('route.geojson')

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg ?? ''} expected ${a} to be within ${tol} of ${b}`)

// ---- timeline ----

test('timeline matches the plan totals', () => {
  const tl = buildTimeline(plan, waypoints, route)
  assert.equal(tl.totalMin, plan.totals.total_min)
  assert.equal(tl.segments.length, 7) // 4 walks and 3 stops
  assert.equal(stopList(tl).length, 3)
})

test('starts at the rover and ends back at it', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const start = stateAt(tl, 0, null)
  near(start.x, 1000, 0.5)
  near(start.y, 900, 0.5)
  const end = stateAt(tl, tl.totalMin, null)
  assert.equal(end.phase, 'done')
  near(end.x, 1000, 0.5)
  near(end.y, 900, 0.5)
})

test('first leg heads north-west (rover to the clay outcrop)', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const s = stateAt(tl, 5, null)
  near(s.heading, 320, 1) // atan2(-500, 600) is about 320 degrees clockwise from north
  assert.equal(s.phase, 'walk')
  assert.equal(s.nextName, 'Clay-bearing outcrop')
})

test('while sampling, "next" is the following stop', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const dwell = stopList(tl)[0]
  const s = stateAt(tl, (dwell.t0 + dwell.t1) / 2, null)
  assert.equal(s.phase, 'stop')
  assert.equal(s.nextName, 'Delta front layers')
  assert.ok(s.nextDist > 0)
})

test('pace is the leg distance over its walking time, and zero when stopped', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const leg = plan.legs[0]
  near(stateAt(tl, 5, null).pace, leg.distance_m / leg.walk_min, 1)
  const dwell = stopList(tl)[0]
  assert.equal(stateAt(tl, (dwell.t0 + dwell.t1) / 2, null).pace, 0)
  assert.equal(stateAt(tl, tl.totalMin, null).pace, 0)
})

test('pace after a storm is the average walking speed', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const storm = { t: 10, d: stateAt(tl, 10, null).d }
  near(stateAt(tl, 12, storm).pace, tl.speed, 1e-9)
})

// ---- solar storm ----

test('storm early on: turn back and reach the rover', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const before = stateAt(tl, 10, null)
  const storm = { t: 10, d: before.d }
  const mid = stateAt(tl, 12, storm)
  assert.equal(mid.phase, 'return')
  assert.ok(mid.d < before.d, 'moving back towards the start')
  const arrive = 10 + before.d / tl.speed
  const end = stateAt(tl, arrive + 1, storm)
  assert.equal(end.phase, 'done')
  near(end.x, 1000, 1)
  near(end.y, 900, 1)
})

test('storm late on: carry on to the rover instead of going back', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const t = tl.totalMin - 10
  const before = stateAt(tl, t, null)
  const storm = { t, d: before.d }
  const after = stateAt(tl, t + 2, storm)
  assert.ok(after.d > before.d, 'moving forward along the route')
  assert.equal(stateAt(tl, t + 60, storm).phase, 'done')
})

test('shelter time is never more than half the route', () => {
  const tl = buildTimeline(plan, waypoints, route)
  for (let t = 0; t <= tl.totalMin; t += 5) {
    assert.ok(stateAt(tl, t, null).shelterMin <= tl.routeLen / 2 / tl.speed + 1e-6)
  }
})

test('trail ends at the current position', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const trail = trailUntil(tl, 30, null)
  const s = stateAt(tl, 30, null)
  assert.deepEqual(trail.at(-1), [s.x, s.y])
})

// ---- real-shaped data ----

// A route with hundreds of points that passes close to (not exactly through) the stops.
function denseRoute(offset) {
  const pts = route.features[0].geometry.coordinates
  const out = []
  for (let i = 1; i < pts.length; i++) {
    for (let k = 0; k < 200; k++) {
      const u = k / 200
      out.push([pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * u + offset, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * u + offset])
    }
  }
  out.push(pts.at(-1))
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: out } }] }
}

test('copes with a dense route that only passes near the stops', () => {
  const tl = buildTimeline(plan, waypoints, denseRoute(8))
  assert.equal(tl.totalMin, plan.totals.total_min)
  const ends = tl.segments.filter((s) => s.type === 'walk').map((s) => s.d1)
  assert.deepEqual([...ends].sort((a, b) => a - b), ends, 'stops are visited in order along the route')
  near(ends.at(-1), tl.routeLen, 0.001)
  const s = stateAt(tl, 100, null)
  assert.ok(Number.isFinite(s.x) && Number.isFinite(s.heading))
})

test('works without a route file (straight lines between stops)', () => {
  const tl = buildTimeline(plan, waypoints, null)
  assert.equal(tl.totalMin, plan.totals.total_min)
  near(stateAt(tl, tl.totalMin, null).x, 1000, 0.5)
})

test('gives up cleanly when plan or waypoints are missing', () => {
  assert.equal(buildTimeline(null, waypoints, route), null)
  assert.equal(buildTimeline(plan, null, route), null)
  assert.equal(buildTimeline({ legs: [] }, waypoints, route), null)
})

// ---- tables ----

test('table parser skips blank lines and bad rows', () => {
  const rows = parseTable('sol,local_hour,dose_rate_usv_h\n40,0,27\n\n40,x,5\n40,1,\n')
  assert.equal(rows.length, 2) // the "x" hour row is dropped
  assert.ok(Number.isNaN(rows[1].dose_rate_usv_h))
  assert.deepEqual(parseTable(''), [])
})

test('radiation uses the fullest sol and the latest earlier hour for gaps', () => {
  const rows = parseTable('sol,local_hour,dose_rate_usv_h\n7,12,500\n40,0,20\n40,6,30\n40,18,90\n40,20,25\n')
  const m = radiationModel(rows)
  assert.equal(m.sol, 40)
  assert.equal(m.rateAt(7), 30) // no row for 07:00: use 06:00
  assert.equal(m.rateAt(19.5), 90)
  assert.equal(m.rateAt(25), 20) // wraps past midnight to 01:00, which is the 00:00 row
  assert.equal(m.stormRate, 90)
  assert.equal(radiationModel([]), null)
})

test('dose over the planned outing is close to the plan figure', () => {
  const rows = parseTable(readFileSync(new URL('../../../data/out/radiation.csv', import.meta.url), 'utf8'))
  const m = radiationModel(rows)
  near(doseTotal(m, plan.totals.total_min, null), plan.radiation_dose_usv, 2)
})

test('a storm raises the dose rate to the storm level', () => {
  const m = radiationModel(parseTable('sol,local_hour,dose_rate_usv_h\n40,0,27\n40,15,90\n'))
  const calm = doseTotal(m, 120, null)
  const stormy = doseTotal(m, 120, { t: 60, d: 0 })
  assert.ok(stormy > calm + 30)
})

test('weather picks the hour and tolerates missing columns', () => {
  const w = weatherModel(parseTable('sol,local_hour,temp_c,pressure_pa,dust_tau\n40,0,-70,740,0.5\n40,12,-20,730,2.1\n'))
  assert.equal(w.at(9).temp, -70)
  assert.equal(w.at(12.5).dust, 2.1)
  const bare = weatherModel(parseTable('sol,local_hour,temp_c\n40,0,-70\n'))
  assert.equal(bare.at(3).pressure, null)
  assert.equal(bare.at(3).dust, null)
})

test('local clock wraps past midnight', () => {
  assert.equal(localClock(0), '09:00')
  assert.equal(localClock(15 * 60 + 30), '00:30')
})

test('space weather: picks the fastest event that reaches Mars', () => {
  const csv = [
    'event_id,type,start_utc,detail,mars_impact,mars_arrival_utc,link',
    'a,CME,2025-06-01T18:00Z,609 km/s,False,,http://x/a',
    'b,CME,2025-06-05T08:12Z,1033 km/s,True,2025-06-07T20:00Z,http://x/b',
    'c,CME,2025-06-06T11:12Z,758 km/s,True,2025-06-09T22:00Z,http://x/c',
  ].join('\n')
  const m = spaceWeatherModel(csv)
  assert.equal(m.total, 3)
  assert.equal(m.hits, 2)
  assert.equal(m.fastest.kms, 1033)
  assert.equal(spaceWeatherModel('event_id,type\n'), null)
  assert.equal(spaceWeatherModel(''), null)
})

// ---- real route data from the route planner (track and storm_replan) ----

// A plan like the planner writes: a track along the route and a storm return from one point on it.
function plannedPlan() {
  const base = buildTimeline(plan, waypoints, route)
  const L = base.routeLen
  const track = Array.from({ length: 11 }, (_, i) => {
    const d = (L * i) / 10
    return { distance_m: d, elev_m: -2500 + i * 10, slope_deg: 5 + i, hazard: i === 5 ? 1 : 0, shelter_min: 15 + Math.min(d, L - d) / 40 }
  })
  const here = stateAt(base, 30, null)
  const home = [base.pts[0][0], base.pts[0][1]]
  const mid = [(here.x + home[0]) / 2, (here.y + home[1]) / 2]
  const len = Math.hypot(here.x - home[0], here.y - home[1])
  const storm_replan = {
    points: [{ x: here.x, y: here.y, route_distance_m: here.d, elapsed_min: 30, return_min: 15 + len / 50, return_distance_m: len, path: [[here.x, here.y], mid, home] }],
  }
  return { plan: { ...plan, totals: { ...plan.totals, ingress_min: 15 }, track, storm_replan }, here, len, home }
}

test('no track in the plan: trackAt is null and shelter time is distance over pace', () => {
  const tl = buildTimeline(plan, waypoints, route)
  assert.equal(trackAt(tl, 100), null)
  const s = stateAt(tl, 5, null)
  near(s.shelterMin, Math.min(s.d, tl.routeLen - s.d) / tl.speed, 1e-6)
})

test('with a track: slope, height and ground class are read at the crew position', () => {
  const { plan: p } = plannedPlan()
  const tl = buildTimeline(p, waypoints, route)
  const L = tl.routeLen
  const g = trackAt(tl, L / 2)
  near(g.elev, -2450, 1e-6)
  near(g.slope, 10, 1e-6)
  assert.equal(g.hazard, 1)
  near(trackAt(tl, L / 20).elev, -2495, 1e-6, 'interpolates between samples')
  assert.equal(trackAt(tl, -50).elev, -2500) // before the start
  near(trackAt(tl, L + 99).elev, -2400, 1e-6) // past the end
})

test('with a track: time back to shelter comes from the planner, and is 0 at the rover', () => {
  const { plan: p } = plannedPlan()
  const tl = buildTimeline(p, waypoints, route)
  const s = stateAt(tl, 5, null)
  near(s.shelterMin, trackAt(tl, s.d).shelter, 1e-9)
  assert.equal(stateAt(tl, tl.totalMin, null).shelterMin, 0)
})

test('a track for a different route is ignored', () => {
  const { plan: p } = plannedPlan()
  const wrong = { ...p, track: p.track.map((r) => ({ ...r, distance_m: r.distance_m * 3 })) }
  const tl = buildTimeline(wrong, waypoints, route)
  assert.equal(tl.track, null)
  assert.equal(tl.stormPts, null)
})

test('bad track rows and bad storm points are skipped', () => {
  const { plan: p } = plannedPlan()
  const messy = {
    ...p,
    track: [{ distance_m: 'x' }, null, ...p.track],
    storm_replan: { points: [{ route_distance_m: 5 }, ...p.storm_replan.points] },
  }
  const tl = buildTimeline(messy, waypoints, route)
  assert.equal(tl.track.length, p.track.length)
  assert.equal(tl.stormPts.length, 1)
  assert.equal(buildTimeline({ ...p, track: 'nope', storm_replan: 5 }, waypoints, route).track, null)
})

test('storm with a plan: the crew follows the planned path home and arrives at the rover', () => {
  const { plan: p, here, len, home } = plannedPlan()
  const tl = buildTimeline(p, waypoints, route)
  const storm = startStorm(tl, 30, here.d)
  assert.ok(storm.ret, 'uses the planner path')
  const walkMin = len / 50 // the planner minutes without the 15 min to get inside
  const first = stateAt(tl, 30, storm)
  assert.equal(first.phase, 'return')
  near(first.shelterMin, walkMin + 15, 0.5)
  const half = stateAt(tl, 30 + walkMin / 2, storm)
  near(half.x, (here.x + home[0]) / 2, len * 0.02) // on the planned path, not the route
  near(half.y, (here.y + home[1]) / 2, len * 0.02)
  const end = stateAt(tl, 30 + walkMin + 1, storm)
  assert.equal(end.phase, 'done')
  near(end.x, home[0], 0.5)
  near(end.y, home[1], 0.5)
  assert.equal(end.shelterMin, 0)
})

test('storm without a usable plan turns round on the route as before', () => {
  const tl = buildTimeline(plan, waypoints, route)
  const s0 = stateAt(tl, 20, null)
  const storm = startStorm(tl, 20, s0.d)
  assert.equal(storm.ret, undefined)
  assert.equal(stateAt(tl, 21, storm).phase, 'return')
})

test('a planned storm path that starts far from the crew is not used', () => {
  const { plan: p, here } = plannedPlan()
  const tl = buildTimeline(p, waypoints, route)
  assert.equal(startStorm(tl, 30, here.d + 0).ret !== undefined, true)
  const far = { ...p, storm_replan: { points: p.storm_replan.points.map((q) => ({ ...q, path: q.path.map(([x, y]) => [x + 900, y]) })) } }
  assert.equal(startStorm(buildTimeline(far, waypoints, route), 30, here.d).ret, undefined)
})

// ---- walking-only plans (routing/plan_route.py since the landing rework) and one-way missions ----

const swapId = (legs, from, to) => legs.map((l) => ({ ...l, from: l.from === from ? to : l.from, to: l.to === from ? to : l.to }))

test('a plan that starts and ends at "start" has 3 stops, not a 4th called start', () => {
  const p = { ...plan, legs: swapId(plan.legs, 'rover', 'start'), start: { id: 'start', name: 'Demo start' } }
  const tl = buildTimeline(p, waypoints, route)
  assert.deepEqual(stopList(tl).map((s) => s.to), ['stop1', 'stop2', 'stop3'])
  assert.equal(tl.totalMin, plan.totals.total_min)
  assert.equal(stateAt(tl, tl.totalMin, null).phase, 'done')
})

test('without a rover waypoint, home is the plan start and keeps its name', () => {
  const p = { ...plan, legs: swapId(plan.legs, 'rover', 'start'), start: { id: 'start', name: 'Demo start' } }
  const noRover = { ...waypoints, features: waypoints.features.filter((f) => f.properties.kind !== 'rover') }
  const tl = buildTimeline(p, noRover, route)
  assert.equal(tl.roverId, 'start')
  assert.equal(tl.roverName, 'Demo start')
  assert.equal(stopList(tl).length, 3)
})

test('a one-way outing ends at its destination without a sampling stop there', () => {
  const p = { ...plan, legs: plan.legs.slice(0, -1) } // rover -> stop1 -> stop2 -> stop3, no way back
  const tl = buildTimeline(p, waypoints, route)
  assert.deepEqual(stopList(tl).map((s) => s.to), ['stop1', 'stop2'])
  assert.equal(stateAt(tl, tl.totalMin, null).phase, 'done')
})
