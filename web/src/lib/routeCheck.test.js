import test from 'node:test'
import assert from 'node:assert/strict'
import { checkRoute, classifyPixel } from './routeCheck.js'

// 4x4 cells over a 40 m square (10 m per cell). Row 0 is north.
function image(paint) {
  const data = new Uint8ClampedArray(4 * 4 * 4)
  for (let row = 0; row < 4; row++)
    for (let col = 0; col < 4; col++) {
      const px = paint(row, col) ?? [34, 170, 90, 0]
      data.set(px, (row * 4 + col) * 4)
    }
  return { data, width: 4, height: 4 }
}
const RED = [220, 50, 50, 170]
const YELLOW = [240, 190, 40, 150]
const line = (...c) => ({ type: 'Feature', geometry: { type: 'LineString', coordinates: c } })

test('classifies the hazard colours', () => {
  assert.equal(classifyPixel(220, 50, 170), 'red')
  assert.equal(classifyPixel(240, 190, 150), 'yellow')
  assert.equal(classifyPixel(34, 170, 0), 'safe')
})

test('a route over see-through cells is all safe', () => {
  const r = checkRoute(line([5, 5], [35, 5]), image(() => null), [40, 40])
  assert.equal(r.redM, 0)
  assert.equal(r.yellowM, 0)
  assert.ok(Math.abs(r.totalM - 30) < 0.01)
})

test('row 0 is north: a red top row catches a route along y = 35 and not y = 5', () => {
  const img = image((row) => (row === 0 ? RED : null))
  assert.ok(checkRoute(line([5, 35], [35, 35]), img, [40, 40]).redM > 29)
  assert.equal(checkRoute(line([5, 5], [35, 5]), img, [40, 40]).redM, 0)
})

test('splits a route across careful and no-go cells', () => {
  // west half yellow, east half red, route runs west to east along y = 15
  const img = image((row, col) => (col < 2 ? YELLOW : RED))
  const r = checkRoute(line([0, 15], [40, 15]), img, [40, 40])
  assert.ok(Math.abs(r.yellowM - 20) < 1)
  assert.ok(Math.abs(r.redM - 20) < 1)
})

test('handles missing or odd input', () => {
  assert.equal(checkRoute(null, image(() => null), [40, 40]), null)
  assert.equal(checkRoute(line([5, 5], [5, 5]), image(() => null), [40, 40]), null)
  assert.equal(checkRoute(line([5, 5], [35, 5]), null, [40, 40]), null)
  assert.ok(checkRoute({ type: 'MultiLineString', coordinates: [[[5, 5], [35, 5]]] }, image(() => null), [40, 40]))
})
