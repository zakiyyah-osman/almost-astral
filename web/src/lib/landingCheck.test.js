import test from 'node:test'
import assert from 'node:assert/strict'
import { landingCheck, messageFor, reasonsFor } from './landingCheck.js'
import { xyOfCell } from './landingData.js'
import { realLanding } from './testGrid.js'

const real = realLanding()

// The first cell of the real tile with this code, and its centre.
function firstCell(g, code, extra = () => true) {
  const s = g.arrays.landing_safety
  for (let i = 0; i < s.length; i++) {
    if (s[i] === code && extra(i)) {
      const row = Math.floor(i / g.width)
      const col = i % g.width
      const [x, y] = xyOfCell(g, row, col)
      return { i, row, col, x, y }
    }
  }
  return null
}

const f32 = (g, name, i) => Number(g.arrays[name][i])

// Each check below writes the expected sentence by hand from the manifest's templates, so the test
// does not reuse landingCheck's own filling code.
function checkMoved(g, r, c) {
  assert.equal(r.status, 'moved')
  assert.equal(g.arrays.landing_safety[r.chosen.row * g.width + r.chosen.col], 0, 'moves onto a safe cell')
  assert.deepEqual([r.chosen.row, r.chosen.col], [g.arrays.nearest_safe[2 * c.i], g.arrays.nearest_safe[2 * c.i + 1]])
  assert.ok(Math.abs(r.moved_m - Math.hypot(r.chosen.x - c.x, r.chosen.y - c.y)) < 1e-12)
  assert.equal(r.moved_text, `Landing spot moved ${r.moved_m.toFixed(1)} m to the nearest safe spot.`)
  assert.equal(r.reasons[0] === r.code_name || r.reasons.includes(r.code_name), true, 'the stored code is one of the reasons')
  for (const m of r.messages) assert.ok(!m.detail.includes('{'), m.detail)
}

test('code 0: a safe click stays where it is', async () => {
  const g = await real
  const c = firstCell(g, 0)
  const r = landingCheck(g, c.x + 1, c.y - 1)
  assert.equal(r.status, 'safe')
  assert.deepEqual([r.chosen.x, r.chosen.y], [c.x + 1, c.y - 1])
  assert.equal(r.moved_m, 0)
  assert.equal(r.moved_text, null)
  assert.deepEqual(r.messages.map((m) => [m.title, m.detail]), [['Safe landing spot', 'The 25 m pad passes every landing rule.']])
})

test('code 1: a marginal click stays and names the limits it is close to', async () => {
  const g = await real
  const c = firstCell(g, 1)
  const r = landingCheck(g, c.x, c.y)
  assert.equal(r.status, 'marginal')
  assert.equal(r.moved_m, 0)
  const s = f32(g, 'pad_slope_deg', c.i)
  const h = f32(g, 'pad_height_range_m', c.i)
  const q = f32(g, 'pad_roughness_m', c.i)
  const d = f32(g, 'hazard_dist_m', c.i)
  const want = []
  if (s > 0.8 * 5) want.push(['Close to the tilt limit', `The pad tilts ${s.toFixed(1)} deg, within 20% of the 5 deg limit.`])
  if (h > 0.8 * 1) want.push(['Close to the height-range limit', `Heights on the pad span ${h.toFixed(2)} m once the tilt is removed, within 20% of the 1 m limit.`])
  if (q > 0.8 * 0.25) want.push(['Close to the roughness limit', `The pad's roughness is ${q.toFixed(2)} m, within 20% of the 0.25 m limit.`])
  if (d < 1.2 * 30) want.push(['Close to a hazard', `The nearest red, too-steep or cliff-edge cell is ${d.toFixed(1)} m from the pad centre, within 20% of the 30 m clearance.`])
  assert.ok(want.length > 0, 'a marginal cell is near at least one limit')
  assert.deepEqual(r.messages.map((m) => [m.title, m.detail]), want)
})

test('a marginal cell with no near_* reason gets the one marginal message', async () => {
  const g = await real
  const m = { pad_slope_deg: 1, pad_roughness_m: 0.01, pad_height_range_m: 0.1, hazard_dist_m: 100 }
  assert.deepEqual(reasonsFor(g, 1, m), ['marginal'])
  assert.equal(messageFor(g, 'marginal', m).detail, 'The pad passes every landing rule, but is within 20% of at least one limit.')
})

test('code 2: too close to the edge of the data, no measured value', async () => {
  const g = await real
  const c = firstCell(g, 2)
  const r = landingCheck(g, c.x, c.y)
  checkMoved(g, r, c)
  assert.equal(r.reasons[0], 'outside_coverage')
  assert.deepEqual([r.messages[0].title, r.messages[0].detail], ['Too close to the edge of the data', 'The 30 m circle around this point does not fit inside the data.'])
})

test('code 3: no terrain data (synthetic when the site has none)', async () => {
  const g = await real
  const c = firstCell(g, 3)
  const nan = { pad_slope_deg: NaN, pad_roughness_m: NaN, pad_height_range_m: NaN, hazard_dist_m: 80 }
  assert.deepEqual(reasonsFor(g, 3, nan), ['no_data'])
  assert.equal(messageFor(g, 'no_data', nan).detail, 'A cell on the 25 m pad has no elevation or slope value.')
  if (c) checkMoved(g, landingCheck(g, c.x, c.y), c)
})

test('code 4: hazard too close, with the distance at the clicked cell', async () => {
  const g = await real
  const c = firstCell(g, 4, (i) => f32(g, 'hazard_dist_m', i) < 30)
  const r = landingCheck(g, c.x, c.y)
  checkMoved(g, r, c)
  const m = r.messages.find((q) => q.reason === 'hazard_or_clearance')
  assert.equal(m.title, 'Hazard too close')
  assert.equal(m.detail, `A red, too-steep or cliff-edge cell is ${f32(g, 'hazard_dist_m', c.i).toFixed(1)} m from the pad centre; at least 30 m is required.`)
})

test('code 4 with the clearance met: the pad fails on its own cells, so no distance is shown', async () => {
  const g = await real
  const c = firstCell(g, 4, (i) => f32(g, 'hazard_dist_m', i) >= 30)
  const m = { pad_slope_deg: 1, pad_roughness_m: 0.01, pad_height_range_m: 0.1, hazard_dist_m: 45 }
  assert.equal(messageFor(g, 'hazard_or_clearance', m).detail, 'A cell on the 25 m pad is not green or cannot be walked on.')
  if (c) assert.equal(landingCheck(g, c.x, c.y).messages[0].detail, 'A cell on the 25 m pad is not green or cannot be walked on.')
})

const measuredCases = [
  [5, 'too_steep', 'pad_slope_deg', 'Too steep to land', (v) => `The pad tilts ${v.toFixed(1)} deg; the limit is 5 deg.`],
  [6, 'height_range', 'pad_height_range_m', 'Ground too uneven', (v) => `Heights on the pad span ${v.toFixed(2)} m once the tilt is removed; the limit is 1 m.`],
  [7, 'too_rough', 'pad_roughness_m', 'Ground too rough', (v) => `The pad's roughness is ${v.toFixed(2)} m; the limit is 0.25 m.`],
]
for (const [code, reason, grid, title, detail] of measuredCases) {
  test(`code ${code}: ${reason}, with the measured value at the clicked cell`, async () => {
    const g = await real
    const c = firstCell(g, code)
    const r = landingCheck(g, c.x, c.y)
    checkMoved(g, r, c)
    assert.equal(r.reasons[0], reason)
    const m = r.messages.find((q) => q.reason === reason)
    assert.equal(m.title, title)
    assert.equal(m.detail, detail(f32(g, grid, c.i)))
  })
}

test('every failure at a cell is listed, lowest code first', async () => {
  const g = await real
  // a too-steep cell (5) whose height range is also over its limit (6)
  const c = firstCell(g, 5, (i) => f32(g, 'pad_height_range_m', i) > 1)
  const r = landingCheck(g, c.x, c.y)
  assert.deepEqual(r.reasons.slice(0, 2), ['too_steep', 'height_range'])
  const codes = r.messages.map((m) => m.code)
  assert.deepEqual(codes, [...codes].sort((a, b) => a - b))
})

test('hazard_dist_m = Infinity: no distance in the text; NaN measures: the no-value sentences', async () => {
  const g = await real
  const inf = { pad_slope_deg: 7, pad_roughness_m: 0.1, pad_height_range_m: 0.5, hazard_dist_m: Infinity }
  assert.deepEqual(reasonsFor(g, 5, inf), ['too_steep'])
  assert.equal(messageFor(g, 'hazard_or_clearance', inf).detail, 'A cell on the 25 m pad is not green or cannot be walked on.')
  assert.equal(reasonsFor(g, 1, inf).includes('near_hazard_or_clearance'), false)
  const nan = { pad_slope_deg: NaN, pad_roughness_m: NaN, pad_height_range_m: NaN, hazard_dist_m: Infinity }
  assert.equal(messageFor(g, 'too_steep', nan).detail, 'The pad tilts more than 5 deg.')
  assert.equal(messageFor(g, 'height_range', nan).detail, 'Heights on the pad span more than 1 m once the tilt is removed.')
  assert.equal(messageFor(g, 'too_rough', nan).detail, "The pad's roughness is more than 0.25 m.")
  assert.deepEqual(reasonsFor(g, 2, nan), ['outside_coverage'])
})

test('a click outside the window chooses nothing', async () => {
  const g = await real
  const r = landingCheck(g, -10, 50)
  assert.equal(r.status, 'outside')
  assert.equal(r.chosen, null)
  assert.deepEqual([r.messages[0].title, r.messages[0].detail], ['Outside the map', 'This point is outside the data, so no landing spot was chosen.'])
})

test('halves round the way JavaScript toFixed does', async () => {
  const g = await real
  assert.equal(messageFor(g, 'too_steep', { pad_slope_deg: 7.25 }).detail, 'The pad tilts 7.3 deg; the limit is 5 deg.') // 7.25 is exact in binary
  assert.equal(messageFor(g, 'too_rough', { pad_roughness_m: 0.375 }).detail, "The pad's roughness is 0.38 m; the limit is 0.25 m.")
})
