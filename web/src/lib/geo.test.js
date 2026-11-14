// Tests for the site grid <-> latitude/longitude conversion. Run with: npm test (from web/).
import test from 'node:test'
import assert from 'node:assert/strict'
import { xyToLatLon, latLonToXY, siteBounds, lon180 } from './geo.js'

// The real site in data/out/layers.json: 2 km square centred on 18.46 N, 77.40 E.
const site = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }

// Expected values from rasterio with the exact projection string of data/grid.py site_proj4
// (+proj=eqc +lat_ts=18.46 +lat_0=18.46 +lon_0=77.4 +R=3396190), computed on 14 Nov.
const POINTS = {
  'south-west corner': { x: 0, y: 0, lat: 18.443129395, lon: 77.382214227 },
  'south-east corner': { x: 2000, y: 0, lat: 18.443129395, lon: 77.417785773 },
  'north-west corner': { x: 0, y: 2000, lat: 18.476870605, lon: 77.382214227 },
  'north-east corner': { x: 2000, y: 2000, lat: 18.476870605, lon: 77.417785773 },
  centre: { x: 1000, y: 1000, lat: 18.46, lon: 77.4 },
}

const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: expected ${a} to be within ${tol} of ${b}`)

for (const [name, p] of Object.entries(POINTS)) {
  test(`${name}: metres -> lat/lon matches the data build, and round-trips`, () => {
    const ll = xyToLatLon(p.x, p.y, site)
    near(ll.lat, p.lat, 1e-8, 'lat') // 1e-8 degrees is about 0.6 mm on Mars
    near(ll.lon, p.lon, 1e-8, 'lon')
    const back = latLonToXY(ll.lat, ll.lon, site)
    near(back.x, p.x, 1e-6, 'x')
    near(back.y, p.y, 1e-6, 'y')
  })
}

test('siteBounds gives the corners of the square', () => {
  const b = siteBounds(site)
  near(b.south, 18.443129395, 1e-8, 'south')
  near(b.north, 18.476870605, 1e-8, 'north')
  near(b.west, 77.382214227, 1e-8, 'west')
  near(b.east, 77.417785773, 1e-8, 'east')
})

test('lon180 turns east longitudes over 180 into negative ones', () => {
  assert.equal(lon180(77.4), 77.4)
  assert.equal(lon180(350), -10)
})
