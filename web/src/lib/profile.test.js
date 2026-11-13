import test from 'node:test'
import assert from 'node:assert/strict'
import { readDem, heightAt, routeProfile } from './profile.js'

// Builds a tiny little-endian float32 TIFF, one strip, the way make_fake.py writes them.
function makeTiff(width, height, values) {
  const entries = 8
  const ifdSize = 2 + entries * 12 + 4
  const dataStart = 8 + ifdSize
  const buf = new ArrayBuffer(dataStart + width * height * 4)
  const dv = new DataView(buf)
  dv.setUint16(0, 0x4949, false)
  dv.setUint16(2, 42, true)
  dv.setUint32(4, 8, true)
  dv.setUint16(8, entries, true)
  const tags = [
    [256, 4, width], [257, 4, height], [258, 3, 32], [259, 3, 1],
    [273, 4, dataStart], [278, 4, height], [279, 4, width * height * 4], [339, 3, 3],
  ]
  tags.forEach(([tag, type, value], i) => {
    const e = 10 + i * 12
    dv.setUint16(e, tag, true)
    dv.setUint16(e + 2, type, true)
    dv.setUint32(e + 4, 1, true)
    if (type === 3) dv.setUint16(e + 8, value, true)
    else dv.setUint32(e + 8, value, true)
  })
  values.forEach((v, i) => dv.setFloat32(dataStart + i * 4, v, true))
  return buf
}

test('readDem reads a float32 TIFF', () => {
  const dem = readDem(makeTiff(3, 2, [1, 2, 3, 4, 5, 6]))
  assert.equal(dem.width, 3)
  assert.equal(dem.height, 2)
  assert.deepEqual(Array.from(dem.data), [1, 2, 3, 4, 5, 6])
})

test('readDem returns null for something that is not a TIFF', () => {
  assert.equal(readDem(new ArrayBuffer(64)), null)
})

test('heightAt: row 0 is the north edge, and outside the grid is NaN', () => {
  // 2 columns x 2 rows over a 2 m x 2 m site: top row (north) is 10, bottom row (south) is 0
  const dem = readDem(makeTiff(2, 2, [10, 10, 0, 0]))
  assert.equal(heightAt(dem, [2, 2], 1, 1.25), 7.5) // a quarter of the way down from the north row centre to the south one
  assert.ok(Number.isNaN(heightAt(dem, [2, 2], -1, 1)))
})

test('routeProfile: a 45 degree ramp reads about 45 degrees', () => {
  // 4x4 grid, 4 m site, height rises 1 m per metre going east
  const row = [0.5, 1.5, 2.5, 3.5]
  const dem = readDem(makeTiff(4, 4, [...row, ...row, ...row, ...row]))
  const prof = routeProfile(dem, [4, 4], [[0.5, 2], [3.5, 2]], 0.5)
  const mid = prof[Math.floor(prof.length / 2)]
  assert.ok(Math.abs(mid.slope - 45) < 1, `slope was ${mid.slope}`)
})
