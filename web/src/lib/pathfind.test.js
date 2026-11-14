import test from 'node:test'
import assert from 'node:assert/strict'
import { slopeDeg } from './terrain.js'
import { DEFAULT_PARAMS, MASK, buildCost, paramsFrom, planLeg, route, searchFrom, timeField, totals, cellAt, centreAt } from './pathfind.js'
import { typedFrom, cellOfXY, xyOfCell } from './landingData.js'
import { planOuting } from './outing.js'
import { xyToLatLon, latLonToXY, distanceBearing } from './geo.js'
import { readDem } from './profile.js'
import { gridCost, readOut, readOutJson, realCost, FLAT_RATE } from './testGrid.js'

const P = { ...DEFAULT_PARAMS }

// ---- golden cases: routing/export_landing.py on the real export ------------------------------

const golden = readOutJson('landing/golden_cases.json')
const real = realCost()

const close = (got, want, name) => {
  if (want === 0) assert.equal(got, 0, `${name}: ${got} should be 0`)
  else assert.ok(Math.abs(got - want) / Math.abs(want) <= 1e-9, `${name}: ${got} vs ${want}`)
}

for (const c of golden.cases) {
  for (const [profile, want] of Object.entries(c.results)) {
    test(`golden ${c.id} ${profile}: same cells and totals as routing`, async () => {
      const { cost } = await real
      const W = cost.width
      const budget = c.budget ?? golden.budget
      const r = route(cost, c.landing_cell[0] * W + c.landing_cell[1], c.dest_cell[0] * W + c.dest_cell[1], golden.profiles[profile].w, budget)
      assert.equal(r.reachable, want.reachable)
      assert.equal(r.reason, want.reason)
      if (!want.reachable) return
      assert.deepEqual(r.cells.map((i) => [Math.floor(i / W), i % W]), want.cells)
      for (const k of ['distance_m', 'walk_min', 'risk_min', 'needed_min']) close(r[k], want[k], k)
      assert.equal(r.over_budget, want.over_budget)
      assert.deepEqual(r.geometry.coordinates[0], c.landing_xy_m)
      assert.deepEqual(r.geometry.coordinates.at(-1), c.dest_xy_m)
    })
  }
}

test('golden cases cover an unreachable and an over-budget destination', () => {
  assert.ok(golden.cases.some((c) => Object.values(c.results).some((r) => !r.reachable)))
  assert.ok(golden.cases.some((c) => Object.values(c.results).some((r) => r.over_budget)))
})

// ---- loader -------------------------------------------------------------------------------------

test('the loader reads every grid at its documented size and type', async () => {
  const { g } = await real
  const m = g.manifest
  for (const [name, spec] of Object.entries(m.grids)) {
    const a = g.arrays[name]
    assert.equal(a.length, g.width * g.height * spec.values_per_cell, name)
    assert.equal(a.constructor.name, { uint8: 'Uint8Array', uint16: 'Uint16Array', float32: 'Float32Array', float64: 'Float64Array' }[spec.dtype])
  }
  // blocked cells: time_rate -1 and risk_rate 0, as the manifest says
  const { mask, time_rate, risk_rate } = g.arrays
  for (let i = 0; i < mask.length; i++) if (mask[i]) assert.ok(time_rate[i] === -1 && risk_rate[i] === 0)
  // the bytes on disk are the values (spot check against a DataView)
  const raw = readOut(`landing/${m.tiles[0].files.time_rate}`)
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength)
  for (const i of [0, 12345, 80000, 159999]) assert.equal(time_rate[i], dv.getFloat64(i * 8, true))
})

test('typed arrays honour the byte order', () => {
  const big = new Uint8Array([0x3f, 0xf0, 0, 0, 0, 0, 0, 0]) // 1.0 as big-endian float64
  assert.equal(typedFrom(big, 'float64', 'big')[0], 1)
  assert.equal(typedFrom(new Uint8Array([1, 2]), 'uint16', 'big')[0], 0x0102)
  assert.equal(typedFrom(new Uint8Array([1, 2]), 'uint16', 'little')[0], 0x0201)
  assert.throws(() => typedFrom(new Uint8Array(3), 'uint16', 'little'))
})

test('cell and xy conversions follow the manifest (row 0 is north)', async () => {
  const { g } = await real
  const c = cellOfXY(g, 337.5, 1672.5)
  assert.deepEqual([c.row, c.col], [65, 67]) // golden pair1 landing
  assert.deepEqual(xyOfCell(g, 65, 67), [337.5, 1672.5])
  assert.equal(cellOfXY(g, -1, 10), null)
  assert.equal(cellOfXY(g, 10, 2000), null) // the north edge is outside
  assert.deepEqual(cellOfXY(g, 0, 0), { row: 399, col: 0, i: 399 * 400 })
})

// ---- the search on small grids -----------------------------------------------------------------

// Flat 60 x 60 grid of 5 m cells with a blocked wall across the middle and one gap in it.
function wallSite({ gap = true } = {}) {
  const W = 60
  const mask = new Uint8Array(W * W)
  for (let r = 0; r < W; r++) for (let c = 28; c <= 31; c++) if (!(gap && r >= 5 && r <= 9)) mask[r * W + c] = 2
  return gridCost({ width: W, height: W, mask })
}

test('the route goes through the gap and never enters a blocked cell', () => {
  const cost = wallSite()
  const leg = planLeg(cost, { x: 50, y: 150 }, { x: 250, y: 150 }, 1)
  assert.ok(leg.ok)
  for (const i of leg.cells) assert.equal(cost.blocked[i], 0)
  assert.ok(Math.max(...leg.points.map((p) => p[1])) > 250, 'it detours north to the gap')
})

test('no gap means walled off (reason 6), a blocked destination gives its mask code', () => {
  const cost = wallSite({ gap: false })
  const leg = planLeg(cost, { x: 50, y: 150 }, { x: 250, y: 150 }, 1)
  assert.equal(leg.ok, false)
  assert.equal(leg.reason, 6)
  assert.match(leg.reason_text, /walled off/)
  const onWall = planLeg(cost, { x: 50, y: 150 }, { x: 150, y: 150 }, 1)
  assert.equal(onWall.reason, 2)
  assert.equal(planLeg(cost, { x: 150, y: 150 }, { x: 50, y: 150 }, 1).reason, 'landing_blocked')
  assert.equal(route(cost, 0, null, 0).reason, 'outside')
})

test('safest never takes more risk than fastest, and fastest is never slower', () => {
  const W = 60
  const riskRate = new Float64Array(W * W)
  for (let r = 20; r <= 40; r++) for (let c = 0; c < W; c++) if (c % 4 < 2) riskRate[r * W + c] = 1
  const cost = gridCost({ width: W, height: W, riskRate })
  const A = { x: 20, y: 150 }
  const B = { x: 280, y: 150 }
  const fast = planLeg(cost, A, B, 0)
  const safe = planLeg(cost, A, B, 5)
  assert.ok(safe.risk_min <= fast.risk_min + 1e-9)
  assert.ok(fast.walk_min <= safe.walk_min + 1e-9)
})

test('totals follow section 15.3: straight and diagonal steps', () => {
  const cost = gridCost({ width: 3, height: 3 })
  const t = totals(cost, [0, 1, 5]) // east, then south-east
  assert.equal(t.distance_m, 5 + 5 * Math.SQRT2)
  assert.ok(Math.abs(t.walk_min - t.distance_m * FLAT_RATE) < 1e-12)
  assert.equal(t.risk_min, 0)
})

test('time field is zero at the source and grows with distance on flat ground', () => {
  const W = 30
  const cost = gridCost({ width: W, height: W })
  const src = cellAt(cost, 75, 75).i
  const t = timeField(cost, src)
  assert.equal(t[src], 0)
  assert.ok(Math.abs(t[cellAt(cost, 75, 125).i] - 50 / 45) < 1e-9)
  assert.deepEqual(centreAt(cost, src), [77.5, 77.5])
})

test('searches are cached per start and weight', () => {
  const cost = gridCost({ width: 10, height: 10 })
  assert.equal(searchFrom(cost, 5, 1), searchFrom(cost, 5, 1))
  assert.notEqual(searchFrom(cost, 5, 1), searchFrom(cost, 5, 0))
})

test('an outing adds up: legs sum to the totals, stops counted once each', () => {
  const W = 60
  const cost = gridCost({ width: W, height: W })
  const pts = [
    { id: 'start', kind: 'start', x: 50, y: 50 },
    { id: 's1', kind: 'stop', x: 250, y: 50 },
    { id: 's2', kind: 'stop', x: 250, y: 250 },
    { id: 'start', kind: 'start', x: 50, y: 50 },
  ]
  const o = planOuting(cost, pts, 1, P, { ingress: true, doseFor: (min) => (min / 60) * 26.67 })
  assert.ok(o.ok)
  const { plan, route: rt } = o
  const walk = plan.legs.reduce((s, l) => s + l.walk_min, 0)
  assert.ok(Math.abs(walk - plan.totals.walk_min) < 0.11)
  assert.equal(plan.totals.stop_min, 2 * P.stop_min_default)
  assert.ok(Math.abs(plan.totals.total_min - (plan.totals.walk_min + plan.totals.stop_min + P.ingress_min)) < 0.11)
  const line = rt.features[0].geometry.coordinates
  let len = 0
  for (let i = 1; i < line.length; i++) len += Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1])
  assert.ok(Math.abs(len - plan.legs.reduce((s, l) => s + l.distance_m, 0)) < 3)
})

test('plan.json assumptions override the copied defaults, and the manifest overrides both', () => {
  const p = paramsFrom({ assumptions: { 'walking.v_flat_kmh': { value: 3.4 } }, budgets: { eva_max_min: 300 } })
  assert.equal(p.v_flat_kmh, 3.4)
  assert.equal(p.eva_max_min, 300)
  assert.match(p.from, /plan\.json/)
  assert.match(paramsFrom(null).from, /copied/)
  const m = paramsFrom(null, { profiles: { safest: { w: 7 } }, budget: { eva_max_min: 360, reserve_pct: 30, ingress_min: 10, stop_min: 20 } })
  assert.equal(m.w_safest, 7)
  assert.equal(m.ingress_min, 10)
  assert.equal(m.stop_min_default, 20)
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
})

test('real export: the team stops from the demo start, every profile, on walkable cells only', async () => {
  const b = readOut('dem.tif')
  const dem = readDem(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength))
  const slope = slopeDeg(dem.data, dem.width, dem.height, 5)
  const { cost } = await realCost({ dem: dem.data, slope, hazard: null, width: dem.width, height: dem.height })
  const plan = readOutJson('plan.json')
  const way = readOutJson('waypoints.geojson')
  const start = { id: 'start', kind: 'start', x: plan.start.xy_m[0], y: plan.start.xy_m[1] }
  const stops = way.features.filter((f) => f.properties.kind === 'stop').map((f) => ({ id: f.properties.id, kind: 'stop', x: f.geometry.coordinates[0], y: f.geometry.coordinates[1] }))
  const pts = [start, ...stops, start]
  for (const prof of ['w_fastest', 'w_balanced', 'w_safest']) {
    const o = planOuting(cost, pts, P[prof], P, { ingress: true })
    assert.ok(o.ok, prof)
    for (const p of o.track) assert.equal(cost.mask[p.i], 0)
    // routing's own planner over the same surface: plan.json profiles, same stop order (as listed),
    // rounded to 0.1. Compare the unrounded leg sums: planOuting rounds each leg to 0.1 before adding.
    const want = plan.profiles[prof.slice(2)]
    const legs = pts.slice(1).map((B, k) => route(cost, cellAt(cost, pts[k].x, pts[k].y).i, cellAt(cost, B.x, B.y).i, P[prof], null))
    const sum = (key) => legs.reduce((s, l) => s + l[key], 0)
    for (const key of ['walk_min', 'distance_m', 'risk_min']) assert.ok(Math.abs(sum(key) - want[key]) <= 0.05 + 1e-9, `${prof} ${key} ${sum(key)} vs plan.json ${want[key]}`)
  }
})

// ---- buildCost: routing's rules on raw grids (the whole-crater grid has no export) ---------------

// Parameters as the app builds them: plan.json assumptions, then the landing manifest.
const exportParams = () => paramsFrom(readOutJson('plan.json'), readOutJson('landing/manifest.json'))

// 12 x 12 flat grid; cells are named [row, col], row 0 = north.
//   [1, 1] no height data (and red: no data wins)     [1, 5] red
//   [5, 5] slope 25 deg, over the 20 deg limit         [8, 2] yellow, [8, 8] slope 15 deg
//   [9, 9] and [10, 10] red, touching at a corner: [9, 10] and [10, 9] are the gap
function smallGrids(cellM) {
  const W = 12
  const dem = new Float32Array(W * W).fill(-2500)
  const slope = new Float32Array(W * W)
  const hazard = new Uint8Array(W * W)
  const at = (r, c) => r * W + c
  dem[at(1, 1)] = NaN
  hazard[at(1, 1)] = 2
  hazard[at(1, 5)] = 2
  slope[at(5, 5)] = 25
  hazard[at(8, 2)] = 1
  slope[at(8, 8)] = 15
  hazard[at(9, 9)] = 2
  hazard[at(10, 10)] = 2
  return { g: { dem, slope, hazard, width: W, height: W, cellM }, at }
}

test('buildCost: mask codes follow routing, the first reason in order winning', () => {
  const p = exportParams()
  const { g, at } = smallGrids(5)
  const cost = buildCost(g, p)
  assert.equal(cost.mask[at(1, 1)], MASK.NODATA)
  assert.equal(cost.mask[at(1, 5)], MASK.RED)
  assert.equal(cost.mask[at(5, 5)], MASK.SLOPE)
  // The 5 m buffer on 5 m cells: the four cells one step away, not the diagonal ones (7.07 m).
  for (const [r, c] of [[4, 5], [6, 5], [5, 4], [5, 6]]) assert.equal(cost.mask[at(r, c)], MASK.BUFFER, `buffer at ${r},${c}`)
  for (const [r, c] of [[4, 4], [4, 6], [6, 4], [6, 6]]) assert.equal(cost.mask[at(r, c)], 0, `no buffer at ${r},${c}`)
  // The gap between two red cells that touch at a corner is sealed on both sides.
  assert.equal(cost.mask[at(9, 10)], MASK.SEALED)
  assert.equal(cost.mask[at(10, 9)], MASK.SEALED)
  assert.equal(cost.mask[at(8, 8)], 0, '15 deg is under the limit')
  assert.equal(cost.mask[at(0, 0)], 0, 'a corner cell is not sealed by the edge')
  for (let i = 0; i < cost.mask.length; i++) {
    assert.equal(cost.blocked[i], cost.mask[i] ? 1 : 0)
    if (cost.mask[i]) assert.deepEqual([cost.timeRate[i], cost.riskRate[i]], [-1, 0])
  }
  // Mask codes and their texts are the landing export's, so a failure reads the same on both grids.
  assert.deepEqual(cost.maskCodes, readOutJson('landing/manifest.json').mask_codes)
  const leg = planLeg(cost, { x: 2.5, y: 2.5 }, { x: 27.5, y: 32.5 }, 1) // to [5, 5]
  assert.deepEqual([leg.ok, leg.reason, leg.reason_text], [false, MASK.SLOPE, 'slope over the limit (20 deg)'])
})

test('buildCost: time and risk rates follow DESIGN sections 4.2 and 5', () => {
  const p = exportParams()
  const { g, at } = smallGrids(5)
  const cost = buildCost(g, p)
  const flat = 60 / (p.v_flat_kmh * 1000) // minutes per metre on flat ground
  assert.equal(cost.timeRate[at(0, 0)], flat)
  // v(S) = v_flat x exp(-k x |S|): at 15 deg, S = tan(15 deg).
  const want = flat / Math.exp(-p.tobler_k * Math.tan((15 * Math.PI) / 180))
  assert.ok(Math.abs(cost.timeRate[at(8, 8)] - want) / want < 1e-12)
  // DESIGN section 5's example: a 10% slope walks at exp(-0.35) = 0.705 of the flat speed.
  const tenPct = buildCost({ ...g, slope: new Float32Array(144).fill((Math.atan(0.1) * 180) / Math.PI), hazard: new Uint8Array(144) }, p)
  assert.ok(Math.abs(flat / tenPct.timeRate[0] - Math.exp(-p.tobler_k * 0.1)) < 1e-6)
  // Risk: yellow, and near red falling linearly to 0 at near_red_radius_m (red at [1, 5]).
  assert.equal(cost.riskRate[at(8, 2)], p.yellow_rate)
  const near = (d) => p.near_red_rate_max * Math.max(0, 1 - d / p.near_red_radius_m)
  assert.ok(Math.abs(cost.riskRate[at(1, 6)] - near(5)) < 1e-12)
  assert.ok(Math.abs(cost.riskRate[at(2, 6)] - near(5 * Math.SQRT2)) < 1e-12)
  assert.ok(Math.abs(cost.riskRate[at(1, 7)] - near(10)) < 1e-12)
  assert.equal(cost.riskRate[at(1, 8)], 0, '15 m away is the end of the ramp')
  assert.equal(cost.riskRate[at(11, 0)], 0)
  assert.ok(Math.abs(cost.riskRate[at(0, 0)] - near(5 * Math.SQRT2)) < 1e-12, 'a no-data cell marked red still counts as red, as in cost.py')
  // The budget is the manifest's, and there is no escape on this surface.
  const b = readOutJson('landing/manifest.json').budget
  assert.deepEqual([cost.budget.usable_min, cost.budget.ingress_min, cost.budget.stop_min], [b.usable_min, b.ingress_min, b.stop_min])
  assert.deepEqual([cost.escape, cost.escapeTimeRate, cost.escapeRiskRate], [null, null, null])
  assert.deepEqual(cost.origin, [0, 0])
  assert.ok(cost.searches instanceof Map)
})

test('buildCost on 40 m cells: the same rules in metres, so the 5 m buffer and the 15 m near-red ramp reach no other cell', () => {
  const p = exportParams()
  const { g, at } = smallGrids(40)
  const cost = buildCost({ ...g, params: p }) // the form lib/craterTasks.js calls
  assert.equal(cost.mask[at(5, 5)], MASK.SLOPE)
  for (const [r, c] of [[4, 5], [6, 5], [5, 4], [5, 6]]) assert.equal(cost.mask[at(r, c)], 0)
  assert.equal(cost.riskRate[at(1, 6)], 0)
  assert.equal(cost.mask[at(9, 10)], MASK.SEALED, 'sealing works on cells, at any size')
  assert.equal(cost.mask[at(1, 1)], MASK.NODATA)
  // A wider buffer does reach: 40 m takes the four neighbours.
  const wide = buildCost(g, { ...p, cliff_buffer_m: 40 })
  for (const [r, c] of [[4, 5], [6, 5], [5, 4], [5, 6]]) assert.equal(wide.mask[at(r, c)], MASK.BUFFER)
  assert.match(wide.maskCodes.find((m) => m.code === MASK.BUFFER).text, /inside the 40 m buffer/)
})

test('buildCost refuses to guess a missing value', () => {
  const { g } = smallGrids(40)
  const { yellow_rate, ...rest } = exportParams()
  assert.throws(() => buildCost(g, rest), /no value for yellow_rate/)
  assert.throws(() => buildCost(g), /no value for/)
})

test('search cache: 24 searches on a site-sized grid, one on a crater-sized grid', () => {
  const small = gridCost({ width: 20, height: 20 })
  for (let i = 0; i < 30; i++) searchFrom(small, i, 0)
  assert.equal(small.searches.size, 24)
  const n = 1600 * 1600
  const big = { width: 1600, height: 1600, cellM: 40, blocked: new Uint8Array(n).fill(1), timeRate: new Float64Array(n), riskRate: new Float64Array(n), searches: new Map() }
  searchFrom(big, 0, 0)
  searchFrom(big, 1, 0)
  assert.equal(big.searches.size, 1)
})
