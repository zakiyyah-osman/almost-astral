import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_PARAMS, paramsFrom, timeField } from './pathfind.js'
import { gridCost, realCost, readOutJson } from './testGrid.js'
import { planOuting } from './outing.js'
import { missionPoints, detourCosts, bestOrder, mineralTargets } from './mission.js'
import { graticule } from './graticule.js'
import { xyToLatLon } from './geo.js'

const P = { ...DEFAULT_PARAMS }

const flat = (W = 60, H = 60) => gridCost({ width: W, height: H })

const mission = (quests) => ({ start: { x: 22, y: 22, name: 'Pad' }, quests, dest: { x: 272, y: 272, name: 'J0' } })

test('mission points: landing, quests in order, destination; one way, no walk back', () => {
  const pts = missionPoints(mission([{ x: 100, y: 50 }, { x: 50, y: 100, stopMin: 10 }]), 25)
  assert.deepEqual(pts.map((p) => p.id), ['start', 'q1', 'q2', 'dest'])
  assert.equal(pts[0].kind, 'start')
  assert.equal(pts[1].stopMin, 25)
  assert.equal(pts[2].stopMin, 10)
  assert.equal(pts[3].stopMin, 25) // the destination stop of routing's one-way budget
  assert.equal(missionPoints(mission([]), 25).length, 2)
  assert.equal(missionPoints({ start: { x: 0, y: 0 }, quests: [] }, 25), null)
})

test('a mission to one destination needs exactly what routing says (golden pair1, every profile)', async () => {
  const { cost } = await realCost()
  const golden = readOutJson('landing/golden_cases.json')
  const c = golden.cases.find((k) => k.id === 'pair1')
  const params = paramsFrom(null, readOutJson('landing/manifest.json'))
  const m = { start: { x: c.landing_xy_m[0], y: c.landing_xy_m[1] }, quests: [], dest: { x: c.dest_xy_m[0], y: c.dest_xy_m[1] } }
  for (const [name, want] of Object.entries(c.results)) {
    const r = planOuting(cost, missionPoints(m, params.stop_min_default), golden.profiles[name].w, params, { ingress: true })
    assert.ok(Math.abs(r.plan.needed_min - want.needed_min) <= 1e-9 * want.needed_min, `${name}: ${r.plan.needed_min} vs ${want.needed_min}`)
    assert.ok(Math.abs(r.plan.exact.distance_m - want.distance_m) <= 1e-9 * want.distance_m)
    assert.equal(r.plan.over_budget, want.over_budget)
  }
})

test('over budget is a warning on the time check', () => {
  const cost = flat()
  const r = planOuting(cost, missionPoints(mission([]), 25), 0, { ...P, usable_min: 30 }, { ingress: true })
  assert.equal(r.plan.over_budget, true)
  const time = r.plan.checks.find((k) => k.id === 'time')
  assert.equal(time.ok, false)
  assert.equal(time.level, 'warn')
})

test('each quest uses its own minutes on site', () => {
  const cost = flat()
  const r = planOuting(cost, missionPoints(mission([{ x: 150, y: 150, stopMin: 7 }]), 25), 1, P)
  assert.equal(r.ok, true)
  assert.equal(r.plan.totals.stop_min, 7 + 25) // the quest's own 7 min, and the destination's 25
})

test('detour cost: a quest on the way costs its stop time, one off the way costs more', () => {
  const cost = flat()
  const cache = new Map()
  const on = detourCosts(cost, mission([{ x: 147, y: 147 }]), 1, P, { cache })
  const off = detourCosts(cost, mission([{ x: 272, y: 22 }]), 1, P, { cache })
  assert.ok(Math.abs(on[0].min - 25) < 2, `on the way: ${on[0].min}`)
  assert.ok(off[0].min > on[0].min + 3)
  assert.ok(off[0].m > 50)
})

test('the leg cache gives the same plan as planning from scratch', () => {
  const cost = flat()
  const pts = missionPoints(mission([{ x: 200, y: 60 }, { x: 60, y: 200 }]), 25)
  const a = planOuting(cost, pts, 5, P)
  const cache = new Map()
  planOuting(cost, pts, 5, P, { cache })
  const b = planOuting(cost, pts, 5, P, { cache })
  assert.deepEqual(a.plan, b.plan)
})

test('best order visits quests along the way instead of zig-zagging', () => {
  const cost = flat()
  const m = mission([{ x: 222, y: 222 }, { x: 72, y: 72 }, { x: 147, y: 147 }])
  assert.deepEqual(bestOrder(cost, m), [1, 2, 0])
})

test('time field from several cells is the time to the nearest of them', () => {
  const cost = flat(20, 20)
  const both = timeField(cost, [0, 399])
  const a = timeField(cost, 0)
  const b = timeField(cost, 399)
  for (const i of [5, 150, 210, 390]) assert.ok(Math.abs(both[i] - Math.min(a[i], b[i])) < 1e-9)
})

test('mineral targets: touching cells of one colour make one area, small specks are dropped', () => {
  const cost = flat(20, 20)
  const data = new Uint8ClampedArray(20 * 20 * 4)
  const paint = (r, c, rgb) => data.set([...rgb, 255], (r * 20 + c) * 4)
  for (let r = 2; r < 6; r++) for (let c = 2; c < 6; c++) paint(r, c, [235, 140, 55]) // 16 cells of carbonate
  paint(15, 15, [120, 200, 70]) // one olivine speck
  const legend = [{ label: 'Olivine', color: '#78c846' }, { label: 'Carbonates', color: '#eb8c37' }]
  const t = mineralTargets({ data, width: 20, height: 20 }, legend, cost, { minCells: 4 })
  assert.equal(t.length, 1)
  assert.equal(t[0].mineral, 'Carbonates')
  assert.equal(t[0].areaM2, 16 * 25)
  assert.ok(Math.abs(t[0].x - 20) <= 5 && Math.abs(t[0].y - 80) <= 5, `${t[0].x}, ${t[0].y}`)
})

test('graticule lines fall on round latitudes and longitudes inside the view', () => {
  const site = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }
  const g = graticule({ x0: 0, x1: 2000, y0: 0, y1: 2000 }, site)
  assert.ok(g.lats.length >= 2 && g.lons.length >= 2)
  for (const l of g.lats) {
    assert.ok(l.y >= -1 && l.y <= 2001)
    assert.ok(Math.abs(xyToLatLon(1000, l.y, site).lat - l.v) < 1e-9)
    assert.ok(Math.abs(l.v / g.step - Math.round(l.v / g.step)) < 1e-6)
  }
  for (const l of g.lons) assert.ok(Math.abs(xyToLatLon(l.x, 1000, site).lon - l.v) < 1e-9)
})
