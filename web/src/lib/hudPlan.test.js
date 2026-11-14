import test from 'node:test'
import assert from 'node:assert/strict'
import { cellOf } from './terrain.js'
import { DEFAULT_PARAMS, timeField, searchFrom } from './pathfind.js'
import { gridCost } from './testGrid.js'
import { planOuting } from './outing.js'
import { hudPlan, pathHome } from './hudPlan.js'
import { buildTimeline, startStorm, stateAt, trackAt } from '../hud/sim.js'
import { waypointsFor } from './outing.js'

const P = { ...DEFAULT_PARAMS }

// 60 x 60 cells of 5 m: ground rising to the east, with a blocked wall and one gap in it.
function site() {
  const W = 60
  const H = 60
  const dem = new Float32Array(W * H)
  const mask = new Uint8Array(W * H)
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) {
    if (c >= 28 && c <= 31 && !(r >= 5 && r <= 9)) mask[r * W + c] = 3
    dem[r * W + c] = c * 0.4
  }
  const slope = new Float32Array(W * H).fill(4.6) // atan(0.4 / 5)
  return gridCost({ width: W, height: H, mask, dem, slope })
}
const storm = (cost, cells, w = 0) => ({ search: searchFrom(cost, cells, w), w })

function mission(cost) {
  const pts = [
    { id: 'start', kind: 'start', name: 'My start', x: 20, y: 150 },
    { id: 'q1', kind: 'stop', name: 'My quest', x: 250, y: 150, stopMin: 10 },
    { id: 'start', kind: 'start', name: 'My start', x: 20, y: 150 },
  ]
  const r = planOuting(cost, pts, P.w_balanced, P, { ingress: true })
  const home = cellOf(20, 150, cost.width, cost.height, cost.cellM).i
  return { pts, r, field: timeField(cost, [home]), storm: storm(cost, [home]) }
}

test('the HUD plan carries height, slope and time back along my own route', () => {
  const cost = site()
  const { r, field, storm: st } = mission(cost)
  assert.ok(r.ok)
  const plan = hudPlan(r.plan, r.track, field, cost, P.ingress_min, 100, st)
  assert.equal(plan.track.length, r.track.length)
  assert.equal(plan.track[0].shelter_min, P.ingress_min) // standing at the start
  const quest = plan.track.reduce((a, b) => (b.x > a.x ? b : a)) // the turn-round point, furthest east
  assert.ok(quest.elev_m > plan.track[0].elev_m + 10) // about 18 m higher: the ground rises to the east
  assert.ok(quest.shelter_min > plan.track[0].shelter_min)
  assert.ok(plan.track.every((row) => row.slope_deg >= 0 && row.shelter_min >= P.ingress_min))
  assert.ok(plan.storm_replan.points.length >= 3)
})

test('the way home follows the search back to the shelter', () => {
  const cost = site()
  const { storm: st } = mission(cost)
  const from = cellOf(250, 150, cost.width, cost.height, cost.cellM).i
  const home = pathHome(cost, st.search, from)
  const [x, y] = home.path[home.path.length - 1]
  assert.ok(Math.hypot(x - 20, y - 150) < 5)
  assert.ok(home.distance_m >= 230)
})

test('the HUD follows my mission, not the team files', () => {
  const cost = site()
  const { pts, r, field, storm: st } = mission(cost)
  const plan = hudPlan(r.plan, r.track, field, cost, P.ingress_min, 100, st)
  const tl = buildTimeline(plan, waypointsFor(pts), r.route)
  assert.ok(tl.track, 'the track matches the route, so slope and height show')
  assert.equal(tl.roverName, 'My start')
  assert.deepEqual(tl.segments.filter((s) => s.type === 'stop').map((s) => s.toName), ['My quest'])
  const mid = tl.segments[0].t1 / 2
  const s = stateAt(tl, mid, null)
  assert.ok(Number.isFinite(trackAt(tl, s.d).slope))
  const storm = startStorm(tl, mid, s.d)
  assert.ok(storm.ret, 'a storm uses the computed way home')
})

// Flat ground 60 x 60 cells of 5 m, with a band of careful ground (risk 1) along the straight way home.
function flatSiteWithBand() {
  const W = 60
  const H = 60
  const hazard = new Uint8Array(W * H)
  const riskRate = new Float64Array(W * H)
  for (let r = 28; r <= 31; r++) for (let c = 10; c <= 50; c++) {
    hazard[r * W + c] = 1
    riskRate[r * W + c] = 1
  }
  return gridCost({ width: W, height: H, hazard, riskRate })
}

test('the way home takes the time the field promises', () => {
  const cost = site()
  const { field, storm: st } = mission(cost)
  for (const [x, y] of [[250, 150], [200, 60], [120, 240]]) {
    const i = cellOf(x, y, cost.width, cost.height, cost.cellM).i
    if (!Number.isFinite(field[i])) continue
    const home = pathHome(cost, st.search, i)
    assert.ok(Math.abs(home.walk_min - field[i]) < 1e-6, `walked ${home.walk_min} min, field says ${field[i]}`)
  }
})

test('a risk-weighted way home stays off careful ground when a short detour avoids it', () => {
  const cost = flatSiteWithBand()
  const shelter = cellOf(20, 150, cost.width, cost.height, cost.cellM).i
  const from = cellOf(270, 150, cost.width, cost.height, cost.cellM).i
  const careful = (path) => path.filter(([x, y]) => cost.hazard[cellOf(x, y, cost.width, cost.height, cost.cellM).i] === 1).length
  const fast = pathHome(cost, searchFrom(cost, [shelter], 0), from)
  const w = P.w_balanced
  const safe = pathHome(cost, searchFrom(cost, [shelter], w), from)
  assert.ok(careful(fast.path) > 20, 'the fastest way runs along the careful band')
  assert.equal(careful(safe.path), 0)
  assert.ok(safe.walk_min < fast.walk_min * 1.05, 'and the detour costs under 5% more walking time')
})

test('the storm return in the HUD plan can follow a risk-weighted field', () => {
  const cost = flatSiteWithBand()
  const home = cellOf(20, 150, cost.width, cost.height, cost.cellM).i
  const pts = [
    { id: 'start', kind: 'start', name: 'Start', x: 20, y: 150 },
    { id: 'q1', kind: 'stop', name: 'Quest', x: 270, y: 150, stopMin: 10 },
    { id: 'start', kind: 'start', name: 'Start', x: 20, y: 150 },
  ]
  const r = planOuting(cost, pts, P.w_balanced, P, { ingress: true })
  assert.ok(r.ok)
  const w = P.w_balanced
  const plan = hudPlan(r.plan, r.track, timeField(cost, [home]), cost, P.ingress_min, 100, storm(cost, [home], w))
  const far = plan.storm_replan.points.reduce((a, b) => (b.return_distance_m > a.return_distance_m ? b : a))
  const careful = far.path.filter(([x, y]) => cost.hazard[cellOf(x, y, cost.width, cost.height, cost.cellM).i] === 1).length
  assert.equal(careful, 0)
  assert.ok(far.return_min > P.ingress_min)
})
