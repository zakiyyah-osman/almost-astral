import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { slopeDeg, hazardFromSlope, cellOf, centreOf } from './terrain.js'
import { DEFAULT_PARAMS, buildCost, paramsFrom, planLeg, speedMPerMin, timeField } from './pathfind.js'
import { recommendLanding, judgeSpot } from './landing.js'
import { planOuting } from './outing.js'
import { xyToLatLon, latLonToXY, distanceBearing } from './geo.js'
import { readDem } from './profile.js'

const P = { ...DEFAULT_PARAMS }

function siteFrom(dem, width, height, cellM) {
  const slope = slopeDeg(dem, width, height, cellM)
  const hazard = hazardFromSlope(slope)
  return buildCost({ dem, slope, hazard, width, height, cellM, params: P })
}

// Flat 60 x 60 grid of 5 m cells with a steep wall across the middle and one gap in it.
function wallSite({ gap = true } = {}) {
  const W = 60
  const H = 60
  const dem = new Float32Array(W * H)
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) {
    const wall = c >= 28 && c <= 31 && !(gap && r >= 5 && r <= 9)
    dem[r * W + c] = wall ? 40 : 0
  }
  return siteFrom(dem, W, H, 5)
}

test('speed on flat ground is v_flat, and falls on slopes the same up and down', () => {
  assert.ok(Math.abs(speedMPerMin(0, P) - 45) < 1e-9) // 2.7 km/h = 45 m/min
  assert.ok(speedMPerMin(0.2, P) < speedMPerMin(0.1, P))
  assert.equal(speedMPerMin(0.2, P), speedMPerMin(-0.2, P))
})

test('slope of a plane matches atan(rise/run), like numpy.gradient', () => {
  const W = 10
  const dem = new Float32Array(W * W)
  for (let r = 0; r < W; r++) for (let c = 0; c < W; c++) dem[r * W + c] = 0.2 * c * 5
  const s = slopeDeg(dem, W, W, 5)
  for (const v of s) assert.ok(Math.abs(v - 11.3099) < 0.01)
})

test('cell and centre conversions agree (row 0 is north)', () => {
  const c = cellOf(12, 290, 60, 60, 5)
  assert.deepEqual([c.row, c.col], [2, 2])
  assert.deepEqual(centreOf(c.i, 60, 60, 5), [12.5, 287.5])
})

test('the route goes through the gap and never enters ground over the slope limit', () => {
  const cost = wallSite()
  const leg = planLeg(cost, { x: 50, y: 150 }, { x: 250, y: 150 }, 1)
  assert.ok(leg.ok)
  assert.equal(leg.metres_by_class[2], 0)
  for (const i of leg.cells) assert.ok(!(cost.slope[i] > P.slope_max_deg))
  const ys = leg.points.map((p) => p[1])
  assert.ok(Math.max(...ys) > 250, 'it detours north to the gap') // gap rows 5-9 are y 250-275
  assert.ok(leg.distance_m > 200)
})

test('no gap means no route, and the app says so instead of crossing the wall', () => {
  const cost = wallSite({ gap: false })
  const leg = planLeg(cost, { x: 50, y: 150 }, { x: 250, y: 150 }, 1)
  assert.equal(leg.ok, false)
  assert.equal(leg.reason, 'unreachable')
})

test('safest never takes more risk than fastest, and fastest is never slower', () => {
  const W = 60
  const dem = new Float32Array(W * W)
  for (let r = 0; r < W; r++) for (let c = 0; c < W; c++) dem[r * W + c] = r >= 20 && r <= 40 ? (c % 4 < 2 ? 1.5 : 0) : 0 // rough band: 10-20 degree cells
  const cost = siteFrom(dem, W, W, 5)
  const A = { x: 20, y: 150 }
  const B = { x: 280, y: 150 }
  const fast = planLeg(cost, A, B, P.w_fastest)
  const safe = planLeg(cost, A, B, P.w_safest)
  assert.ok(fast.ok && safe.ok)
  assert.ok(safe.risk_min <= fast.risk_min + 1e-9)
  assert.ok(fast.walk_min <= safe.walk_min + 1e-9)
})

test('a start on blocked ground is moved to the nearest walkable cell', () => {
  const cost = wallSite()
  const leg = planLeg(cost, { x: 150, y: 100 }, { x: 50, y: 100 }, 1) // x 150 is on the wall
  assert.ok(leg.ok)
  assert.ok(leg.snapM[0] > 0 && leg.snapM[0] <= 100)
})

test('time field is zero at the source and grows with distance on flat ground', () => {
  const W = 30
  const cost = siteFrom(new Float32Array(W * W), W, W, 5)
  const src = cellOf(75, 75, W, W, 5).i
  const t = timeField(cost, src)
  assert.equal(t[src], 0)
  const far = cellOf(75, 125, W, W, 5).i
  assert.ok(Math.abs(t[far] - 50 / 45) < 1e-6) // 50 m at 45 m/min
})

test('an outing adds up: legs sum to the totals, stops counted once each', () => {
  const W = 60
  const cost = siteFrom(new Float32Array(W * W), W, W, 5)
  const pts = [
    { id: 'rover', kind: 'rover', x: 50, y: 50 },
    { id: 's1', kind: 'stop', x: 250, y: 50 },
    { id: 's2', kind: 'stop', x: 250, y: 250 },
    { id: 'rover', kind: 'rover', x: 50, y: 50 },
  ]
  const o = planOuting(cost, pts, 1, P, { ingress: true, doseFor: (min) => (min / 60) * 26.67 })
  assert.ok(o.ok)
  const { plan, route } = o
  const walk = plan.legs.reduce((s, l) => s + l.walk_min, 0)
  assert.ok(Math.abs(walk - plan.totals.walk_min) < 0.11)
  assert.equal(plan.totals.stop_min, 2 * P.stop_min_default)
  assert.ok(Math.abs(plan.totals.total_min - (plan.totals.walk_min + plan.totals.stop_min + P.ingress_min)) < 0.11)
  const line = route.features[0].geometry.coordinates
  let len = 0
  for (let i = 1; i < line.length; i++) len += Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1])
  assert.ok(Math.abs(len - plan.legs.reduce((s, l) => s + l.distance_m, 0)) < 3)
  assert.equal(plan.radiation_dose_usv, Math.round(((plan.totals.walk_min + plan.totals.stop_min) / 60) * 26.67))
})

test('plan.json assumptions override the copied defaults', () => {
  const p = paramsFrom({ assumptions: { 'walking.v_flat_kmh': { value: 3.4 } }, budgets: { eva_max_min: 300 } })
  assert.equal(p.v_flat_kmh, 3.4)
  assert.equal(p.eva_max_min, 300)
  assert.equal(p.tobler_k, 3.5)
  assert.match(p.from, /plan\.json/)
  assert.match(paramsFrom(null).from, /copied/)
})

test('landing spots are flat, clear and spread apart', () => {
  const W = 80
  const dem = new Float32Array(W * W)
  for (let r = 0; r < W; r++) for (let c = 0; c < W; c++) dem[r * W + c] = c < 40 ? 0.6 * c * 5 : 0 // west half 31 degrees, east half flat
  const cost = siteFrom(dem, W, W, 5)
  const spots = recommendLanding(cost, [{ x: 300, y: 200 }, { x: 300, y: 200 }])
  assert.ok(spots.length >= 1)
  for (const s of spots) {
    assert.ok(s.x > 200, 'on the flat half')
    assert.ok(s.meanSlope <= 5)
  }
  for (let a = 0; a < spots.length; a++) for (let b = a + 1; b < spots.length; b++) assert.ok(Math.hypot(spots[a].x - spots[b].x, spots[a].y - spots[b].y) >= 250)
  assert.equal(judgeSpot(cost, 50, 200).ok, false)
})

test('grid metres and latitude / longitude round-trip, and distances use the Mars radius', () => {
  const site = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }
  const c = xyToLatLon(1000, 1000, site)
  assert.ok(Math.abs(c.lat - 18.46) < 1e-12 && Math.abs(c.lon - 77.4) < 1e-12)
  const ll = xyToLatLon(1700, 300, site)
  const back = latLonToXY(ll.lat, ll.lon, site)
  assert.ok(Math.abs(back.x - 1700) < 1e-6 && Math.abs(back.y - 300) < 1e-6)
  const north = xyToLatLon(1000, 2000, site)
  assert.ok(Math.abs(distanceBearing(c, north).distanceM - 1000) < 0.5)
  assert.ok(Math.abs(distanceBearing(c, north).bearingDeg) < 1e-6)
})

test('real HiRISE terrain: every route stays under the slope limit and the totals add up', () => {
  const read = (f) => {
    const b = readFileSync(new URL(`../../../data/out/${f}`, import.meta.url))
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)
  }
  const dem = readDem(read('dem.tif'))
  const way = JSON.parse(new TextDecoder().decode(read('waypoints.geojson')))
  const layers = JSON.parse(new TextDecoder().decode(read('layers.json')))
  const cellM = layers.site.grid.cell_m
  const cost = siteFrom(dem.data, dem.width, dem.height, cellM)
  const pts = way.features.map((f) => ({ id: f.properties.id, kind: f.properties.kind, x: f.geometry.coordinates[0], y: f.geometry.coordinates[1] }))
  pts.push(pts[0])
  for (const prof of ['w_fastest', 'w_balanced', 'w_safest']) {
    const o = planOuting(cost, pts, P[prof], P, { ingress: true })
    assert.ok(o.ok, prof)
    assert.equal(o.plan.metres_nogo, 0, `${prof} enters no-go ground`)
    assert.ok(o.plan.max_slope_deg <= P.slope_max_deg, `${prof} max slope ${o.plan.max_slope_deg}`)
    assert.ok(o.plan.totals.walk_min > 60 && o.plan.totals.walk_min < 200, `${prof} walk ${o.plan.totals.walk_min}`)
  }
  const spots = recommendLanding(cost, [pts[1], pts[pts.length - 2]])
  assert.ok(spots.length > 0)
  for (const s of spots) assert.ok(s.meanSlope <= 5)
})
