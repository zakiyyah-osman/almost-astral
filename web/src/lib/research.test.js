import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { inflateSync } from 'node:zlib'
import { MINERAL_CLASSES, squareToXY, squareToLatLon, squareBounds, classForPixel } from './research.js'
import { MARS_RADIUS_M } from './geo.js'

const SITE = { extent_m: [2000, 2000], center_lat: 18.46, center_lon_east: 77.4 }
const KM_PER_DEG_LAT = (MARS_RADIUS_M * Math.PI) / 180 / 1000

test('the 12 km square shares its centre with our site', () => {
  assert.deepEqual(squareToXY(6, 6, SITE), { x: 1000, y: 1000 })
  const c = squareToLatLon(6, 6, SITE)
  assert.ok(Math.abs(c.lat - 18.46) < 1e-9 && Math.abs(c.lon - 77.4) < 1e-9)
  const b = squareBounds(SITE)
  assert.ok(Math.abs((b.north - b.south) * KM_PER_DEG_LAT - 12) < 1e-6) // 12 km tall on Mars
})

test('a pixel is named after the closest legend colour, and blanks are ignored', () => {
  for (const c of MINERAL_CLASSES) {
    const n = parseInt(c.color.slice(1), 16)
    assert.equal(classForPixel((n >> 16) & 255, (n >> 8) & 255, n & 255).id, c.id)
  }
  assert.equal(classForPixel(0, 0, 0, 0), null) // transparent
  assert.equal(classForPixel(20, 20, 200), null) // not a legend colour
})

// Reads an 8-bit RGBA PNG (no interlace) into { w, h, px }.
function readPng(path) {
  const buf = readFileSync(path)
  let p = 8
  let w = 0
  let h = 0
  const idat = []
  while (p < buf.length) {
    const len = buf.readUInt32BE(p)
    const type = buf.toString('ascii', p + 4, p + 8)
    const body = buf.subarray(p + 8, p + 8 + len)
    if (type === 'IHDR') {
      w = body.readUInt32BE(0)
      h = body.readUInt32BE(4)
      assert.equal(body[8], 8)
      assert.equal(body[9], 6) // RGBA
    }
    if (type === 'IDAT') idat.push(body)
    p += 12 + len
  }
  const raw = inflateSync(Buffer.concat(idat))
  const px = new Uint8Array(w * h * 4)
  const stride = w * 4
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)]
    for (let x = 0; x < stride; x++) {
      const v = raw[y * (stride + 1) + 1 + x]
      const a = x >= 4 ? px[y * stride + x - 4] : 0
      const b = y > 0 ? px[(y - 1) * stride + x] : 0
      const c = x >= 4 && y > 0 ? px[(y - 1) * stride + x - 4] : 0
      const pa = Math.abs(b - c)
      const pb = Math.abs(a - c)
      const pc = Math.abs(a + b - 2 * c)
      const pred = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f]
      px[y * stride + x] = (v + pred) & 255
    }
  }
  return { w, h, px }
}

test('the traced map is the note’s 20 m grid, and each mineral’s area is close to the note’s table', () => {
  const { w, h, px } = readPng(new URL('../assets/minerals_12km.png', import.meta.url))
  assert.equal(w, 600)
  assert.equal(h, 600)
  const counts = {}
  for (let i = 0; i < px.length; i += 4) {
    const c = classForPixel(px[i], px[i + 1], px[i + 2], px[i + 3], 0)
    if (c) counts[c.id] = (counts[c.id] ?? 0) + 1
  }
  for (const c of MINERAL_CLASSES) {
    const km2 = (counts[c.id] ?? 0) * 0.0004 // 20 m cells
    assert.ok(Math.abs(km2 - c.areaKm2) / c.areaKm2 < 0.15, `${c.id}: traced ${km2.toFixed(2)} km², note ${c.areaKm2} km²`)
  }
})

test('the augite areas sit in the south-east and the carbonate in the north-west, as on the note’s map', () => {
  const { px } = readPng(new URL('../assets/minerals_12km.png', import.meta.url))
  const centre = (id) => {
    let sx = 0
    let sy = 0
    let n = 0
    for (let i = 0; i < px.length; i += 4) {
      const c = classForPixel(px[i], px[i + 1], px[i + 2], px[i + 3], 0)
      if (c?.id !== id) continue
      const k = i / 4
      sx += k % 600
      sy += Math.floor(k / 600)
      n++
    }
    return { east: (sx / n) * 0.02, north: 12 - (sy / n) * 0.02 } // km from the south-west corner
  }
  const aug = centre('augite')
  assert.ok(aug.east > 8 && aug.north < 4, JSON.stringify(aug))
  const carb = centre('carbonate')
  assert.ok(carb.east < 5 && carb.north > 6, JSON.stringify(carb))
})
