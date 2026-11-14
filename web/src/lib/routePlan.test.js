import test from 'node:test'
import assert from 'node:assert/strict'
import { planRoutes } from './routePlan.js'
import { paramsFrom, route, cellAt } from './pathfind.js'
import { gridCost, realCost, readOutJson } from './testGrid.js'

const params = paramsFrom(null, readOutJson('landing/manifest.json'))

test('no start or no destination: no routes yet, but minutes back as soon as there is a start', () => {
  const cost = gridCost({ width: 40, height: 40 })
  const none = planRoutes(cost, params, { start: null, quests: [], dest: null })
  assert.equal(none.points, null)
  assert.equal(none.back, null)
  const startOnly = planRoutes(cost, params, { start: { x: 20, y: 20 }, quests: [], dest: null })
  assert.equal(startOnly.results, null)
  assert.equal(startOnly.back[cellAt(cost, 20, 20).i], 0)
})

test('the demo can use plan.json start as home with no trip start', () => {
  const cost = gridCost({ width: 40, height: 40 })
  const r = planRoutes(cost, params, { start: null, quests: [], dest: null }, { home: { x: 100, y: 100 } })
  assert.equal(r.back[cellAt(cost, 100, 100).i], 0)
})

test('Team outing and My mission give the same routes from the same points (one shared workflow)', async () => {
  const { cost } = await realCost()
  const plan = readOutJson('plan.json')
  const trip = { start: { x: plan.start.xy_m[0], y: plan.start.xy_m[1], name: 'Start' }, quests: [{ x: 1562.5, y: 1307.5, name: 'Stop 1', stopMin: 25 }], dest: { x: 1867.5, y: 972.5, name: 'J0' } }
  const a = planRoutes(cost, params, trip)
  const b = planRoutes(cost, params, { ...trip, start: { ...trip.start, name: 'Landing' } })
  for (const p of ['fastest', 'balanced', 'safest']) {
    assert.ok(a.results[p].ok, p)
    assert.equal(a.results[p].plan.needed_min, b.results[p].plan.needed_min)
    assert.deepEqual(a.results[p].route.features[0].geometry.coordinates, b.results[p].route.features[0].geometry.coordinates)
  }
})

test('one way, with the budget rule: walk + ingress + each quest + 25 at the destination', async () => {
  const { cost } = await realCost()
  const s = { x: 1017.5, y: 1112.5, name: 'Start' }
  const q = { x: 1562.5, y: 1307.5, name: 'Quest', stopMin: 10 }
  const d = { x: 1867.5, y: 972.5, name: 'J0' }
  const r = planRoutes(cost, params, { start: s, quests: [q], dest: d }).results.balanced
  const leg1 = route(cost, cellAt(cost, s.x, s.y).i, cellAt(cost, q.x, q.y).i, 1, null)
  const leg2 = route(cost, cellAt(cost, q.x, q.y).i, cellAt(cost, d.x, d.y).i, 1, null)
  assert.deepEqual(r.plan.legs.map((l) => l.to), ['q1', 'dest']) // no walk back
  assert.ok(Math.abs(r.plan.needed_min - (leg1.walk_min + leg2.walk_min + 15 + 10 + 25)) < 1e-9)
  assert.equal(r.plan.over_budget, r.plan.needed_min > 252)
})

test('the routes follow every change of start, quest or destination', async () => {
  const { cost } = await realCost()
  const base = { start: { x: 1017.5, y: 1112.5 }, quests: [], dest: { x: 1867.5, y: 972.5 } }
  const a = planRoutes(cost, params, base).results.balanced.plan.needed_min
  const moved = planRoutes(cost, params, { ...base, dest: { x: 1562.5, y: 1307.5 } }).results.balanced.plan.needed_min
  const withQuest = planRoutes(cost, params, { ...base, quests: [{ x: 1562.5, y: 1307.5, stopMin: 25 }] }).results.balanced.plan.needed_min
  assert.notEqual(a, moved)
  assert.ok(withQuest > a)
})

// ---- stage 3: the HUD follows the picked route, every value from its cells ----
import { hudFor } from './routePlan.js'
import { outingResults, outingWaypoints } from './teamOuting.js'
import { waypointsFor } from './outing.js'
import { buildTimeline } from '../hud/sim.js'
import { readDem } from './profile.js'
import { slopeDeg } from './terrain.js'
import { readOut } from './testGrid.js'

const terrainCost = async () => {
  const b = readOut('dem.tif')
  const dem = readDem(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength))
  const slope = slopeDeg(dem.data, dem.width, dem.height, 5)
  return (await realCost({ dem: dem.data, slope, hazard: new Uint8Array(dem.width * dem.height), width: dem.width, height: dem.height })).cost
}

test('a computed route: the HUD track is the route cells on the terrain grids, home is the user start', async () => {
  const cost = await terrainCost()
  const trip = { start: { x: 1017.5, y: 1112.5, name: 'Start' }, quests: [], dest: { x: 1867.5, y: 972.5, name: 'J0' } }
  const out = planRoutes(cost, params, trip)
  const active = out.results.balanced
  const waypoints = waypointsFor(out.waypointPoints)
  const hud = hudFor({ isDemo: false, active, cost, back: out.back, stormField: out.stormField, ingress: 15, waypoints })
  assert.equal(hud.route, active.route)
  assert.equal(hud.plan.track.length, active.track.length)
  for (let k = 0; k < active.track.length; k += 25) assert.equal(hud.plan.track[k].elev_m, Math.round(cost.dem[active.track[k].i] * 10) / 10)
  assert.match(hud.plan.storm_replan.source, /web route-finder/)
  const tl = buildTimeline(hud.plan, waypoints, hud.route)
  assert.equal(tl.roverId, 'start')
  assert.equal(tl.roverName, 'Start')
})

test('the demo route: the HUD plan comes from the route file cells, not from plan.json track or storm return', async () => {
  const cost = await terrainCost()
  const plan = readOutJson('plan.json')
  const routes = Object.fromEntries(Object.entries(plan.profiles).map(([id, p]) => [id, readOutJson(p.file)]))
  const demo = { plan, routes, waypoints: readOutJson('waypoints.geojson') }
  const home = planRoutes(cost, params, { start: null, quests: [], dest: null }, { home: { x: plan.start.xy_m[0], y: plan.start.xy_m[1] } })
  const results = outingResults(plan, routes, cost, home.back, 15)
  const waypoints = outingWaypoints(plan, demo.waypoints)
  for (const id of ['balanced', 'safest']) {
    const hud = hudFor({ isDemo: true, demo, active: results[id], cost, back: home.back, stormField: home.stormField, ingress: 15, waypoints })
    assert.equal(hud.route, routes[id], `${id}: the HUD walks the picked file`)
    assert.ok(hud.plan.from_route_cells)
    assert.notDeepEqual(hud.plan.track, plan.track)
    assert.notEqual(hud.plan.storm_replan.source, plan.storm_replan?.source)
    const walked = hud.plan.legs.reduce((s, l) => s + l.distance_m, 0)
    assert.ok(Math.abs(walked - plan.profiles[id].distance_m) < 10, `${id}: ${walked} m vs ${plan.profiles[id].distance_m}`)
    const tl = buildTimeline(hud.plan, waypoints, hud.route)
    assert.equal(tl.roverName, 'Demo start')
    assert.deepEqual(tl.segments.filter((s) => s.type === 'stop').map((s) => s.to), ['stop1', 'stop2', 'stop3'])
  }
})

test('no route: no HUD plan, so the HUD shows no metrics', async () => {
  const cost = await terrainCost()
  const red = cost.mask.findIndex((m) => m === 2)
  const dest = { x: ((red % 400) + 0.5) * 5, y: (400 - Math.floor(red / 400) - 0.5) * 5, name: 'J0' }
  const out = planRoutes(cost, params, { start: { x: 1017.5, y: 1112.5 }, quests: [], dest })
  assert.equal(out.results.balanced.ok, false)
  assert.equal(hudFor({ isDemo: false, active: out.results.balanced, cost, back: out.back, stormField: out.stormField, ingress: 15, waypoints: null }), null)
})
