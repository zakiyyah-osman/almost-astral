// Elevation and slope along the route, read straight from dem.tif (see CONTRACT.md: float32 heights in metres).
// No libraries: a small reader for plain (uncompressed, striped or tiled-free) float32 TIFFs, which is what
// make_fake.py writes. If the real DEM is written another way (compressed, tiled), readDem returns null and the
// chart says the profile is not available instead of breaking the page.

const TYPE_BYTES = { 3: 2, 4: 4 } // SHORT, LONG

// Returns { width, height, data: Float32Array } with row 0 at the north edge, or null if the file is not supported.
export function readDem(buffer) {
  try {
    const dv = new DataView(buffer)
    const order = dv.getUint16(0, false)
    const le = order === 0x4949 // 'II'
    if (!le && order !== 0x4d4d) return null
    if (dv.getUint16(2, le) !== 42) return null // not a classic TIFF
    const ifd = dv.getUint32(4, le)
    const n = dv.getUint16(ifd, le)
    const tags = {}
    for (let i = 0; i < n; i++) {
      const e = ifd + 2 + i * 12
      const tag = dv.getUint16(e, le)
      const type = dv.getUint16(e + 2, le)
      const count = dv.getUint32(e + 4, le)
      const size = TYPE_BYTES[type]
      if (!size) continue
      const base = count * size <= 4 ? e + 8 : dv.getUint32(e + 8, le)
      const values = []
      for (let k = 0; k < count; k++) {
        values.push(size === 2 ? dv.getUint16(base + k * 2, le) : dv.getUint32(base + k * 4, le))
      }
      tags[tag] = values
    }
    const width = tags[256]?.[0]
    const height = tags[257]?.[0]
    const bits = tags[258]?.[0]
    const compression = tags[259]?.[0] ?? 1
    const format = tags[339]?.[0] ?? 1
    const offsets = tags[273]
    const counts = tags[279]
    const rowsPerStrip = tags[278]?.[0] ?? height
    const samples = tags[277]?.[0] ?? 1
    if (tags[324] || !offsets) return null // tiled
    if (!width || !height || bits !== 32 || format !== 3 || compression !== 1 || samples !== 1) return null

    const data = new Float32Array(width * height)
    for (let s = 0; s < offsets.length; s++) {
      const firstRow = s * rowsPerStrip
      const rows = Math.min(rowsPerStrip, height - firstRow)
      const len = Math.min(rows * width * 4, counts?.[s] ?? Infinity)
      for (let k = 0; k < len / 4; k++) data[firstRow * width + k] = dv.getFloat32(offsets[s] + k * 4, le)
    }
    return { width, height, data }
  } catch {
    return null
  }
}

// Height in metres at (x, y) on the site grid (metres east / north of the south-west corner), bilinear.
// Returns NaN outside the grid or where the DEM has no data.
export function heightAt(dem, extent, x, y) {
  const col = (x / extent[0]) * dem.width - 0.5
  const row = dem.height - (y / extent[1]) * dem.height - 0.5
  const c0 = Math.floor(col)
  const r0 = Math.floor(row)
  if (c0 < 0 || r0 < 0 || c0 + 1 >= dem.width || r0 + 1 >= dem.height) return NaN
  const fc = col - c0
  const fr = row - r0
  const at = (r, c) => dem.data[r * dem.width + c]
  const z00 = at(r0, c0)
  const z01 = at(r0, c0 + 1)
  const z10 = at(r0 + 1, c0)
  const z11 = at(r0 + 1, c0 + 1)
  const z = z00 * (1 - fc) * (1 - fr) + z01 * fc * (1 - fr) + z10 * (1 - fc) * fr + z11 * fc * fr
  return Number.isFinite(z) && z > -1e6 && z < 1e6 ? z : NaN
}

// Samples the path every stepM metres. pts is a list of [x, y]; cum is the distance along the path at each vertex.
// Returns [{ d, z, slope }]: d in metres along the path, z the height, slope in degrees (from the height change
// either side of the sample, so it is a rise over a distance of about 2 steps, not a cell-by-cell slope).
export function routeProfile(dem, extent, pts, stepM = 10) {
  if (!dem || !pts || pts.length < 2) return []
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  const total = cum[cum.length - 1]
  const out = []
  let seg = 1
  for (let d = 0; d <= total + 1e-9; d += stepM) {
    while (seg < pts.length - 1 && cum[seg] < d) seg++
    const len = cum[seg] - cum[seg - 1] || 1
    const f = Math.min(Math.max((d - cum[seg - 1]) / len, 0), 1)
    const x = pts[seg - 1][0] + (pts[seg][0] - pts[seg - 1][0]) * f
    const y = pts[seg - 1][1] + (pts[seg][1] - pts[seg - 1][1]) * f
    out.push({ d, z: heightAt(dem, extent, x, y), slope: NaN })
  }
  for (let i = 0; i < out.length; i++) {
    const a = out[Math.max(i - 1, 0)]
    const b = out[Math.min(i + 1, out.length - 1)]
    const run = b.d - a.d
    if (run > 0 && Number.isFinite(a.z) && Number.isFinite(b.z)) out[i].slope = (Math.atan(Math.abs(b.z - a.z) / run) * 180) / Math.PI
  }
  return out
}
