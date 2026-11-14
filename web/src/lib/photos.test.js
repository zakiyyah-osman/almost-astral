// Tests for the ground-photo helpers. Run with: npm test (from web/).
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { photosFrom, setPhotos, nearestPhoto, photosAlongPath, describeNearest } from './photos.js'
import { MARS_RADIUS_M } from './geo.js'

// Three made-up photos on a line running east along 18.46 N (fixed data, so the tests do not
// depend on what is in data/out). One degree of longitude here is about 56.2 km.
const M_PER_DEG_LON = (Math.PI / 180) * MARS_RADIUS_M * Math.cos((18.46 * Math.PI) / 180)
const lonAt = (eastM) => 77.4 + eastM / M_PER_DEG_LON
const fc = {
  type: 'FeatureCollection',
  features: [0, 500, 1000].map((e, i) => ({
    type: 'Feature',
    properties: { file: `p${i}.jpg`, sol: 400 + i, camera: 'Navcam (left)', image_id: `ID${i}`, credit: 'NASA/JPL-Caltech' },
    geometry: { type: 'Point', coordinates: [lonAt(e), 18.46] },
  })),
}
const photos = photosFrom(fc)
const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `expected ${a} to be within ${tol} of ${b}`)

test('nearestPhoto finds the closest photo and its distance', () => {
  const r = nearestPhoto(18.46, lonAt(480), photos)
  assert.equal(r.photo.file, 'p1.jpg')
  near(r.distance_m, 20, 0.5)
  assert.equal(nearestPhoto(18.46, lonAt(0), photos).photo.file, 'p0.jpg')
  near(nearestPhoto(18.46, lonAt(0), photos).distance_m, 0, 1e-6)
})

test('nearestPhoto far from every photo: still answers, and describeNearest says it is not this place', () => {
  const r = nearestPhoto(18.46 + 0.05, lonAt(1000), photos) // about 3 km north of p2
  assert.equal(r.photo.file, 'p2.jpg')
  near(r.distance_m, 2964, 5)
  const d = describeNearest(r)
  assert.equal(d.show, false)
  assert.match(d.text, /^No ground photos here: the nearest is 3\.0 km away/)
  assert.equal(describeNearest(nearestPhoto(18.46, lonAt(480), photos)).show, true)
})

test('nearestPhoto with no photos is null', () => {
  assert.equal(nearestPhoto(18.46, 77.4, []), null)
  assert.equal(describeNearest(null).show, false)
})

test('photosAlongPath: a straight path picks the photos near it, in walking order', () => {
  // Walk west from 1200 m east to 100 m west, 30 m north of the photo line.
  const north = 18.46 + 30 / ((Math.PI / 180) * MARS_RADIUS_M)
  const path = [
    { lat: north, lon: lonAt(1200) },
    { lat: north, lon: lonAt(-100) },
  ]
  const hits = photosAlongPath(path, 100, photos)
  assert.deepEqual(hits.map((h) => h.photo.file), ['p2.jpg', 'p1.jpg', 'p0.jpg'])
  hits.forEach((h) => near(h.distance_m, 30, 0.5))
  near(hits[0].along_m, 200, 1)
  near(hits[2].along_m, 1200, 1)
  // GeoJSON-order points work too, and a tighter limit leaves them out.
  assert.equal(photosAlongPath(path.map((p) => [p.lon, p.lat]), 100, photos).length, 3)
  assert.equal(photosAlongPath(path, 20, photos).length, 0)
})

test('photosAlongPath: a path far from every photo gives an empty list', () => {
  const far = 18.46 + 0.02 // about 1.2 km north
  assert.deepEqual(photosAlongPath([{ lat: far, lon: lonAt(0) }, { lat: far, lon: lonAt(1000) }], 100, photos), [])
  assert.deepEqual(photosAlongPath([], 100, photos), [])
})

test('the real photos.geojson loads, and every photo has an image, sol, camera and credit', () => {
  const real = setPhotos(JSON.parse(readFileSync(new URL('../../../data/out/photos.geojson', import.meta.url), 'utf8')))
  assert.ok(real.length >= 10)
  for (const p of real) {
    assert.ok(p.file && p.url && Number.isFinite(p.sol) && p.camera && p.credit && p.image_id)
    assert.ok(Number.isFinite(p.lat) && Number.isFinite(p.lon))
  }
  // The default photo set is now the real one: the site centre has a photo within 300 m.
  const r = nearestPhoto(18.46, 77.4)
  assert.ok(r && r.distance_m < 300)
})
