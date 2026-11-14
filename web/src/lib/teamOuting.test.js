import test from 'node:test'
import assert from 'node:assert/strict'
import { outingResults, outingWaypoints, sampleLine, unverifiedWarning, planExtras } from './teamOuting.js'
import { buildTimeline } from '../hud/sim.js'
import { gridCost, readOutJson } from './testGrid.js'

const plan = readOutJson('plan.json')
const waypoints = readOutJson('waypoints.geojson')
const routes = Object.fromEntries(Object.entries(plan.profiles).map(([id, p]) => [id, readOutJson(p.file)]))

test('the outing starts at plan.json start, and the rover waypoint is dropped', () => {
  const w = outingWaypoints(plan, waypoints)
  assert.deepEqual(w.features[0].geometry.coordinates, plan.start.xy_m)
  assert.equal(w.features[0].properties.kind, 'start')
  assert.equal(w.features[0].properties.name, plan.start.name)
  assert.ok(!w.features.some((f) => f.properties.kind === 'rover'))
  assert.equal(w.features.length, 1 + waypoints.features.filter((f) => f.properties.kind === 'stop').length)
})

test('cards come from plan.json profiles and each profile draws its own file', () => {
  const r = outingResults(plan, routes, null, null)
  for (const [id, p] of Object.entries(plan.profiles)) {
    assert.ok(r[id].ok)
    assert.equal(r[id].route, routes[id])
    assert.equal(r[id].plan.legs[0].distance_m, p.distance_m)
    assert.equal(r[id].plan.totals.walk_min, p.walk_min)
    assert.equal(r[id].plan.totals.total_min, p.total_min)
    assert.equal(r[id].plan.risk_min, p.risk_min)
    assert.ok(Number.isNaN(r[id].plan.metres_careful), 'rows plan.json does not give stay empty')
  }
  assert.equal(outingResults(plan, { balanced: routes.balanced }, null, null).fastest.ok, false)
})

test('the route charts sample the file route every cell', () => {
  const cost = gridCost({ width: 400, height: 400 })
  const s = sampleLine(cost, routes.balanced.features[0].geometry.coordinates)
  assert.ok(Math.abs(s.at(-1).d - plan.profiles.balanced.distance_m) < 1, `${s.at(-1).d} vs ${plan.profiles.balanced.distance_m}`)
  for (let k = 1; k < s.length; k++) assert.ok(s[k].d - s[k - 1].d <= 5 + 1e-9)
})

test('the HUD and the timeline go home to plan.json start, not to the rover waypoint', () => {
  const tl = buildTimeline(plan, outingWaypoints(plan, waypoints), routes.balanced)
  assert.equal(tl.roverId, 'start')
  assert.equal(tl.roverName, 'Demo start')
  // even with the old rover waypoint still in the list
  const withRover = buildTimeline(plan, waypoints, routes.balanced)
  assert.equal(withRover.roverId, 'start')
  assert.deepEqual(tl.pts[0], plan.start.xy_m)
})

test('the unverified-stops warning and the Plan extras come from plan.json', () => {
  assert.match(unverifiedWarning(plan), /unverified/)
  const e = planExtras(plan)
  assert.equal(e.max_slope_deg, Math.max(...plan.legs.map((l) => l.max_slope_deg)))
  assert.ok(e.ascent_m > 0 && e.descent_m > 0)
})
