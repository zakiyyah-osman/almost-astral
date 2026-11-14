import test from 'node:test'
import assert from 'node:assert/strict'
import { escapeSearch, planWithEscape, zoneOf, passableRegions } from './escape.js'
import { planRoutes } from './routePlan.js'
import { planOuting } from './outing.js'
import { DEFAULT_PARAMS, cellAt, reasonText, route } from './pathfind.js'
import { missionPoints } from './mission.js'
import { gridCost, FLAT_RATE } from './testGrid.js'

const P = { ...DEFAULT_PARAMS, usable_min: 252 }
const W = 40
const at = (r, c) => r * W + c
const xy = (r, c) => ({ x: (c + 0.5) * 5, y: (W - r - 0.5) * 5 })

// A 40 x 40 grid of 5 m cells with a red zone (mask 2) over rows/cols 10-20, and escape rates in it
// (three times slower than flat ground, risk 1). extra(mask) adds more blocked cells.
function site(extra = () => {}, { rates = true } = {}) {
  const mask = new Uint8Array(W * W)
  for (let r = 10; r <= 20; r++) for (let c = 10; c <= 20; c++) mask[at(r, c)] = 2
  extra(mask)
  const cost = gridCost({ width: W, height: W, mask })
  cost.maskCodes = [{ code: 1, text: 'no DEM data' }, { code: 2, text: 'red hazard cell' }, { code: 6, text: 'passable, but walled off from the start by blocked cells' }]
  if (rates) {
    cost.escapeTimeRate = new Float64Array(W * W).fill(-1)
    cost.escapeRiskRate = new Float64Array(W * W)
    for (let i = 0; i < W * W; i++) if (mask[i] === 2) {
      cost.escapeTimeRate[i] = 3 * FLAT_RATE
      cost.escapeRiskRate[i] = 1
    }
  }
  return cost
}
const trip = (s, d, quests = []) => ({ start: { ...xy(...s), name: 'Start' }, quests, dest: { ...xy(...d), name: 'J0' } })
const plan = (cost, t, w = 1) => planWithEscape(cost, missionPoints(t, 25), w, P, { ingress: true, reasonText: (r) => reasonText(cost, r) })

// The shortest escape walk among exits in the destination's region, worked out by brute force.
function shortestValidExit(cost, startCell, destCell) {
  const zone = zoneOf(cost, startCell)
  const rates = { timeRate: Float64Array.from(cost.timeRate), riskRate: Float64Array.from(cost.riskRate) }
  for (const i of zone.cells) {
    rates.timeRate[i] = cost.escapeTimeRate[i]
    rates.riskRate[i] = cost.escapeRiskRate[i]
  }
  const s = escapeSearch(cost, zone, rates, 0)
  const reg = passableRegions(cost)
  return Math.min(...s.exits.filter((e) => reg[e] === reg[destCell]).map((e) => s.g[e]))
}

test('start outside a red zone: the normal search, no blocked cell entered, same as without escape', () => {
  const cost = site()
  const t = trip([5, 5], [30, 30])
  const a = planRoutes(cost, P, t, { escape: true }).results.balanced
  const b = planOuting(cost, missionPoints(t, 25), P.w_balanced, P, { ingress: true })
  assert.ok(a.ok && !a.plan.escape)
  assert.deepEqual(a.route.features[0].geometry.coordinates, b.route.features[0].geometry.coordinates)
  for (const p of a.track) assert.equal(cost.mask[p.i], 0)
})

test('start inside: the escape stays in the zone, takes the shortest exit, and the route never re-enters blocked ground', () => {
  const cost = site()
  const t = trip([15, 18], [15, 35])
  const r = plan(cost, t)
  assert.ok(r.ok, r.reason_text)
  const esc = r.plan.escape
  const zone = zoneOf(cost, at(15, 18))
  assert.ok(esc.cells.slice(0, -1).every((i) => zone.has[i]), 'every escape cell but the exit is in the zone')
  const exit = esc.cells.at(-1)
  assert.equal(cost.mask[exit], 0, 'the exit is passable')
  // shortest: the east edge, 3 cells away (19, 20, then the exit at column 21)
  assert.equal(exit % W, 21)
  // the rest of the route: never a blocked cell, the zone included
  for (const p of r.track.filter((q) => !q.escape)) assert.equal(cost.mask[p.i], 0)
  // the escape counts in the totals and is drawn as its own feature
  const after = route(cost, exit, at(15, 35), P.w_balanced, null)
  assert.ok(Math.abs(r.plan.exact.walk_min - (esc.walk_min + after.walk_min)) < 1e-9, 'total walk = escape + the normal route from the exit')
  assert.ok(Math.abs(r.plan.exact.distance_m - (esc.distance_m + after.distance_m)) < 1e-9)
  assert.ok(r.plan.needed_min > esc.walk_min + 15 + 25)
  assert.equal(r.plan.legs[0].escape, true)
  assert.equal(r.route.features[1].properties.escape, true)
  assert.ok(r.plan.checks.some((c) => c.id === 'escape' && c.level === 'warn'))
  assert.ok(r.plan.checks.find((c) => c.id === 'nogo').ok, 'the escape is not counted as no-go walking')
})

test('the shortest exit cannot reach the destination: a longer one that can is chosen', () => {
  // An enclosed pocket east of the zone (no-data walls, mask 1): the nearest exit opens into it.
  const cost = site((m) => {
    for (let r = 11; r <= 19; r++) m[at(r, 24)] = 1
    for (let c = 21; c <= 24; c++) {
      m[at(11, c)] = 1
      m[at(19, c)] = 1
    }
  })
  const reg = passableRegions(cost)
  assert.notEqual(reg[at(15, 21)], reg[at(15, 35)], 'the pocket is walled off')
  const r = plan(cost, trip([15, 19], [15, 35]))
  assert.ok(r.ok, r.reason_text)
  const exit = r.plan.escape.cells.at(-1)
  assert.equal(reg[exit], reg[at(15, 35)], 'the chosen exit reaches the destination')
  const zone = zoneOf(cost, at(15, 19))
  const rates = { timeRate: Float64Array.from(cost.timeRate), riskRate: Float64Array.from(cost.riskRate) }
  for (const i of zone.cells) {
    rates.timeRate[i] = cost.escapeTimeRate[i]
    rates.riskRate[i] = cost.escapeRiskRate[i]
  }
  const s = escapeSearch(cost, zone, rates, 0)
  const pocketBest = Math.min(...s.exits.filter((e) => reg[e] !== reg[at(15, 35)]).map((e) => s.g[e]))
  assert.ok(pocketBest < s.g[exit], 'a shorter exit existed, into the pocket')
  assert.equal(s.g[exit], shortestValidExit(cost, at(15, 19), at(15, 35)), 'and the chosen one is the shortest valid exit')
})

test('no exit leads to the destination: a clear failure', () => {
  // A no-data ring two cells outside the zone: every exit is trapped between the zone and the ring.
  const cost = site((m) => {
    for (let k = 7; k <= 23; k++) m[at(7, k)] = m[at(23, k)] = m[at(k, 7)] = m[at(k, 23)] = 1
  })
  const r = plan(cost, trip([15, 15], [30, 30]))
  assert.equal(r.ok, false)
  assert.equal(r.reason, 'no_exit')
  assert.match(r.reason_text, /no way out of the red zone/)
})

test('without routing escape rates, a start inside a red zone says so', () => {
  const cost = site(() => {}, { rates: false })
  const r = planRoutes(cost, P, trip([15, 15], [30, 30]), { escape: true }).results.balanced
  assert.equal(r.ok, false)
  assert.equal(r.reason, 'escape_unavailable')
  assert.match(r.reason_text, /escape_time_rate/)
})

test('My mission never escapes: a start in a red zone is simply blocked', () => {
  const cost = site()
  const r = planRoutes(cost, P, trip([15, 15], [30, 30])).results.balanced
  assert.equal(r.ok, false)
  assert.equal(r.reason, 'landing_blocked')
})

test('minutes back and the storm return go to the red-zone exit, not into the zone', () => {
  const cost = site()
  const out = planRoutes(cost, P, trip([15, 18], [15, 35]), { escape: true })
  assert.ok(out.inZone)
  const exit = out.results.balanced.plan.escape.exit
  assert.equal(out.back[cellAt(cost, exit.x, exit.y).i], 0)
  assert.deepEqual(out.waypointPoints.map((p) => p.id), ['start', 'exit', 'dest'])
})

test('the HUD timeline walks the escape first and does not stop at the exit', async () => {
  const { buildTimeline, stopList, stateAt } = await import('../hud/sim.js')
  const { waypointsFor } = await import('./outing.js')
  const cost = site()
  const out = planRoutes(cost, P, trip([15, 18], [15, 35], [{ ...xy(5, 30), name: 'Quest', stopMin: 10 }]), { escape: true })
  const r = out.results.balanced
  assert.ok(r.ok, r.reason_text)
  const tl = buildTimeline({ ...r.plan, start: { id: 'start', name: 'Start' } }, waypointsFor(out.waypointPoints), r.route)
  assert.deepEqual(stopList(tl).map((s) => s.to), ['q1'], 'only the side quest is a sampling stop')
  assert.equal(tl.segments[0].to, 'exit')
  const atExit = stateAt(tl, tl.segments[0].t1, null)
  const exit = r.plan.escape.exit
  assert.ok(Math.hypot(atExit.x - exit.x, atExit.y - exit.y) < 1, 'the crew is at the exit when the escape ends')
})

test('the real export: a Team outing start on a red cell walks out, or says why it cannot', async () => {
  const { realCost } = await import('./testGrid.js')
  const { cost } = await realCost()
  const red = cost.mask.findIndex((m) => m === 2)
  const [x, y] = [((red % 400) + 0.5) * 5, (400 - Math.floor(red / 400) - 0.5) * 5]
  const r = planRoutes(cost, P, { start: { x, y, name: 'Start' }, quests: [], dest: { x: 1017.5, y: 1112.5, name: 'J0' } }, { escape: true }).results.balanced
  if (r.ok) assert.ok(r.plan.escape.walk_min > 0)
  else assert.ok(['start_too_steep', 'no_exit'].includes(r.reason), r.reason)
})

// ---- golden escape cases: routing/escape.py on the real export (DESIGN section 17.4) ----
import { readOutJson, realCost as realLandingCost } from './testGrid.js'
import { paramsFrom } from './pathfind.js'

const goldenEscape = readOutJson('landing/golden_escape_cases.json')
const realEscape = realLandingCost()
const near = (got, want, name) => {
  if (want === 0) assert.equal(got, 0, `${name}: ${got} should be 0`)
  else assert.ok(Math.abs(got - want) / Math.abs(want) <= 1e-9, `${name}: ${got} vs ${want}`)
}

test('the real export has the escape grids and the manifest escape block', async () => {
  const { cost } = await realEscape
  assert.ok(cost.escapeTimeRate && cost.escapeRiskRate)
  assert.deepEqual(cost.escape.zone_codes, [2, 3, 4, 5])
  assert.equal(reasonText(cost, 'start_too_steep'), `Too steep to walk out of here: over ${cost.escape.max_slope_deg}°`)
})

for (const c of goldenEscape.cases) {
  for (const [name, want] of Object.entries(c.results)) {
    test(`golden escape ${c.id} ${name}: same escape, exit, route and totals as routing`, async () => {
      const { cost } = await realEscape
      const W = cost.width
      const params = paramsFrom(null, { profiles: goldenEscape.profiles, budget: goldenEscape.budget })
      const pts = [
        { id: 'start', kind: 'start', name: 'Start', x: c.start_xy_m[0], y: c.start_xy_m[1] },
        { id: 'dest', kind: 'stop', name: 'J0', x: c.dest_xy_m[0], y: c.dest_xy_m[1] },
      ]
      const r = planWithEscape(cost, pts, goldenEscape.profiles[name].w, params, { ingress: true, reasonText: (k) => reasonText(cost, k) })
      assert.equal(r.ok, want.ok)
      if (!want.ok) {
        assert.equal(r.reason, want.reason)
        assert.equal(r.status, want.status)
        return
      }
      const rc = (i) => [Math.floor(i / W), i % W]
      const esc = r.plan.escape
      assert.deepEqual(esc.cells.map(rc), want.escape.cells)
      assert.deepEqual([esc.exit.x, esc.exit.y], want.escape.exit_xy_m)
      for (const k of ['distance_m', 'walk_min', 'risk_min']) near(esc[k], want.escape[k], `escape ${k}`)
      const after = r.plan.after_escape
      assert.deepEqual(after.cells.map(rc), want.route.cells)
      for (const k of ['distance_m', 'walk_min', 'risk_min']) near(after[k], want.route[k], `route ${k}`)
      for (const k of ['distance_m', 'walk_min', 'risk_min']) near(r.plan.exact[k], want.total[k], `total ${k}`)
      near(r.plan.needed_min, want.total.needed_min, 'needed_min')
      assert.equal(r.plan.over_budget, want.total.over_budget)
    })
  }
}
