import test from 'node:test'
import assert from 'node:assert/strict'
import { MARKERS, MINERAL_CLASSES, SAMPLE_GROUPS, REFERENCES, squareToXY, squareToLatLon, squareBounds, classForPixel } from './research.js'
import { latLonToXY, MARS_RADIUS_M } from './geo.js'

const SITE = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }
const KM_PER_DEG_LAT = (MARS_RADIUS_M * Math.PI) / 180 / 1000

test('the 12 km square shares its centre with our site', () => {
  assert.deepEqual(squareToXY(6, 6, SITE), { x: 1000, y: 1000 })
  const c = squareToLatLon(6, 6, SITE)
  assert.ok(Math.abs(c.lat - 18.46) < 1e-9 && Math.abs(c.lon - 77.4) < 1e-9)
  const b = squareBounds(SITE)
  assert.ok(Math.abs((b.north - b.south) * KM_PER_DEG_LAT - 12) < 1e-6) // 12 km tall on Mars
})

test('stars from the note’s table sit at its reported offsets from the centre', () => {
  // Offsets from page 2 of the note (km east, km north of the centre).
  const reported = { bunsen_peak: [-4.1, 1.9], turquoise_bay: [-3.0, 1.7], sapphire_canyon: [-5.3, 2.2], montdenier: [2.5, -1.7], quartier: [2.3, -1.6] }
  for (const [group, [e, n]] of Object.entries(reported)) {
    const m = MARKERS.find((k) => k.group === group)
    assert.equal(m.method, 'table')
    const ll = squareToLatLon(m.east, m.north, SITE)
    const xy = latLonToXY(ll.lat, ll.lon, SITE)
    assert.ok(Math.abs((xy.x - 1000) / 1000 - e) < 0.001, `${group} east`)
    assert.ok(Math.abs((xy.y - 1000) / 1000 - n) < 0.001, `${group} north`)
  }
})

test('the samples inside our walk land inside the 2 km site', () => {
  for (const m of MARKERS.filter((k) => k.group === 'wildcat_and_skinner_ridge' || k.group === 'mageik_and_kukaklek')) {
    const { x, y } = squareToXY(m.east, m.north, SITE)
    assert.ok(x >= 0 && x <= 2000 && y >= 0 && y <= 2000, m.label)
  }
})

test('every star has its sample group, and every group cites a reference', () => {
  for (const m of MARKERS.filter((k) => k.kind === 'star')) assert.ok(SAMPLE_GROUPS[m.group], m.label)
  for (const g of Object.values(SAMPLE_GROUPS)) for (const r of g.refs) assert.ok(REFERENCES[r], r)
})

test('a pixel is named after the closest legend colour, and blanks are ignored', () => {
  for (const c of MINERAL_CLASSES) {
    const n = parseInt(c.color.slice(1), 16)
    assert.equal(classForPixel((n >> 16) & 255, (n >> 8) & 255, n & 255).id, c.id)
  }
  assert.equal(classForPixel(0, 0, 0, 0), null) // transparent
  assert.equal(classForPixel(20, 20, 200), null) // not a legend colour
})
