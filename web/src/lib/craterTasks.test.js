// Tests for the whole-crater grid jobs (craterTasks.js), on a small made-up grid in the same file
// format as data/out/crater/ (grid.json + Int16 height, Uint8 hazard, Uint8 slope). Run: npm test.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { DEFAULT_PARAMS } from './pathfind.js'
import { createCraterState, runCraterTask, gridsFrom } from './craterTasks.js'
import { xyToLatLon, latLonToXY } from './geo.js'

// The 2 km site, and a 4 km x 4 km "crater" grid of 40 m cells (100 x 100) centred on the same point.
const site = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }
const N = 100
const header = {
  rows: N, cols: N, cell_m: 40, row0: 'north', byte_order: 'little',
  projection: { center_lat: 18.46, center_lon_east: 77.4 },
  height: { nodata: -32768 }, hazard: { nodata_class: 2 }, slope: { scale: 0.25, nodata: 255 },
}

// Flat ground at -2500 m with a no-go wall (hazard 2) down column 70, open only in rows 10-14, and a
// patch of cells with no height data at rows 80-89, columns 20-29.
function files() {
  const height = new Int16Array(N * N).fill(-2500)
  const hazard = new Uint8Array(N * N)
  const slope = new Uint8Array(N * N)
  for (let r = 0; r < N; r++) {
    if (r < 10 || r > 14) hazard[r * N + 70] = 2
    for (let c = 20; c < 30; c++) if (r >= 80 && r < 90) {
      height[r * N + c] = -32768
      hazard[r * N + c] = 2
      slope[r * N + c] = 255
    }
  }
  return { height: height.buffer, hazard: hazard.buffer, slope: slope.buffer }
}

function loaded() {
  const s = createCraterState()
  runCraterTask(s, 'load', { header, ...files(), params: DEFAULT_PARAMS, site, radRows: [], backgroundUsvH: 640 / 24 })
  return s
}

// Site metres of the centre of crater cell (row, col).
const at = (row, col) => {
  const frame = { extent_m: [N * 40, N * 40], center_lat: 18.46, center_lon_east: 77.4 }
  const ll = xyToLatLon((col + 0.5) * 40, (N - row - 0.5) * 40, frame)
  return latLonToXY(ll.lat, ll.lon, site)
}

test('gridsFrom: no-data heights and slopes become NaN, the rest are metres and degrees', () => {
  const g = gridsFrom(header, ...Object.values(files()))
  assert.equal(g.dem[0], -2500)
  assert.ok(Number.isNaN(g.dem[85 * N + 25]) && Number.isNaN(g.slope[85 * N + 25]))
  assert.equal(g.hazard[0 * N + 70], 2)
  assert.throws(() => gridsFrom({ ...header, rows: N + 1 }, ...Object.values(files())), /do not match/)
})

test('probe: terrain anywhere on the crater grid, no data, and outside it', () => {
  const s = loaded()
  const p = at(50, 10)
  const v = runCraterTask(s, 'probe', { ...p, shelters: [at(50, 5)] })
  assert.equal(v.inCrater, true)
  assert.equal(v.z, -2500)
  assert.equal(v.hazard, 0)
  assert.ok(v.back > 3 && v.back < 6, `5 cells (200 m) at 45 m/min is about 4.4 min, got ${v.back}`)
  assert.deepEqual(runCraterTask(s, 'probe', { ...at(85, 25), shelters: [] }), { inCrater: true, noData: true })
  assert.deepEqual(runCraterTask(s, 'probe', { x: 9000, y: 9000, shelters: [] }), { inCrater: false })
})

test('probe with lazyBack: terrain at once, minutes back after the worker\'s "field" job', () => {
  const s = loaded()
  const shelters = [at(50, 5)]
  const first = runCraterTask(s, 'probe', { ...at(50, 10), shelters, lazyBack: true })
  assert.equal(first.z, -2500)
  assert.equal(first.back, null)
  assert.equal(first.backPending, true)
  assert.deepEqual(s.wantShelters, shelters)
  runCraterTask(s, 'field', { shelters })
  const later = runCraterTask(s, 'probe', { ...at(50, 10), shelters, lazyBack: true })
  assert.ok(later.back > 3 && !later.backPending)
})

test('plans: a route across the wall goes through the gap, avoids no-data, and comes back in site metres', () => {
  const s = loaded()
  const A = { id: 'a', name: 'A', kind: 'rover', ...at(50, 40) }
  const B = { id: 'b', name: 'B', kind: 'stop', ...at(50, 90) }
  const out = runCraterTask(s, 'plans', { points: [A, B], ingress: false, shelters: [A], profiles: [{ id: 'balanced', w: 1 }] })
  const r = out.balanced
  assert.equal(r.ok, true)
  assert.equal(r.grid, 'crater')
  // The wall is open only in rows 10-14: every point near column 70 must be up there.
  const nearWall = r.track.filter((p) => Math.abs(p.x - at(50, 70).x) < 30)
  assert.ok(nearWall.length > 0 && nearWall.every((p) => p.y > at(15, 70).y - 20), 'crosses the wall through the gap')
  assert.ok(r.track.every((p) => p.hazard !== 2), 'never on a do-not-enter cell')
  // Site metres: the route starts at A and its line matches the track.
  const [x0, y0] = r.route.features[0].geometry.coordinates[0]
  assert.ok(Math.hypot(x0 - A.x, y0 - A.y) < 30)
  assert.ok(r.track[0].back < 1 && r.furthest > 10, 'minutes back grow away from the start')
})

test('plans: a destination inside the no-data patch has no route', () => {
  const s = loaded()
  const A = { id: 'a', name: 'A', kind: 'rover', ...at(50, 40) }
  const B = { id: 'b', name: 'B', kind: 'stop', ...at(85, 25) }
  const r = runCraterTask(s, 'plans', { points: [A, B], ingress: false, shelters: [A], profiles: [{ id: 'balanced', w: 1 }] }).balanced
  assert.equal(r.ok, false)
  assert.equal(r.reason, 'end')
})

test('the real crater grid files match their grid.json', { skip: !existsSync(new URL('../../../data/out/crater/grid.json', import.meta.url)) }, () => {
  const dir = new URL('../../../data/out/crater/', import.meta.url)
  const h = JSON.parse(readFileSync(new URL('grid.json', dir), 'utf8'))
  const read = (f) => { const b = readFileSync(new URL(f.replace('crater/', ''), dir)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length) }
  const g = gridsFrom(h, read(h.height.file), read(h.hazard.file), read(h.slope.file))
  assert.equal(g.dem.length, h.rows * h.cols)
  const finite = g.dem.filter(Number.isFinite)
  assert.ok(finite.length > 0.9 * g.dem.length && Math.min(...finite.slice(0, 1e5)) > -9000)
})
