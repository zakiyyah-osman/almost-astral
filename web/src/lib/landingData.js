// Reads routing's landing export (data/out/landing/, routing/docs/DESIGN.md sections 14-16):
// manifest.json, then every binary grid of every tile it lists. Raw values, no header, row-major,
// row 0 = the north edge, dtype and byte order from the manifest. Tiles are copied into
// window-sized arrays, so the rest of the app indexes one grid: i = row * width + col.

const TYPES = {
  uint8: Uint8Array,
  uint16: Uint16Array,
  float32: Float32Array,
  float64: Float64Array,
}

const LITTLE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1

// A typed array of `dtype` from raw bytes in `order` ('little' or 'big').
export function typedFrom(bytes, dtype, order) {
  const T = TYPES[dtype]
  if (!T) throw new Error(`landing export: unknown dtype ${dtype}`)
  const size = T.BYTES_PER_ELEMENT
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  if (u8.byteLength % size) throw new Error(`landing export: ${u8.byteLength} bytes is not a whole number of ${dtype}`)
  const n = u8.byteLength / size
  const out = new T(n)
  if (size === 1 || (order === 'little') === LITTLE) {
    new Uint8Array(out.buffer).set(u8)
    return out
  }
  const view = new DataView(u8.buffer, u8.byteOffset, u8.byteLength)
  const little = order === 'little'
  const get = { 2: 'getUint16', 4: dtype === 'float32' ? 'getFloat32' : 'getUint32', 8: 'getFloat64' }[size]
  for (let k = 0; k < n; k++) out[k] = view[get](k * size, little)
  return out
}

// fetchJson(path) and fetchBytes(path) take paths relative to data/out (e.g. 'landing/manifest.json').
// fetchBytes returns an ArrayBuffer or Uint8Array, or null when the file is missing.
export async function loadLanding(fetchJson, fetchBytes, dir = 'landing') {
  const manifest = await fetchJson(`${dir}/manifest.json`)
  const { width, height, cell_m: cellM, origin_m: origin } = manifest.grid
  const order = manifest.byte_order
  const arrays = {}
  for (const [name, spec] of Object.entries(manifest.grids)) {
    const T = TYPES[spec.dtype]
    if (!T) throw new Error(`landing export: unknown dtype ${spec.dtype} for ${name}`)
    arrays[name] = new T(width * height * spec.values_per_cell)
  }
  await Promise.all(
    manifest.tiles.flatMap((tile) =>
      Object.entries(manifest.grids).map(async ([name, spec]) => {
        const file = tile.files?.[name]
        if (!file) throw new Error(`landing export: tile ${tile.index} has no ${name}`)
        const bytes = await fetchBytes(`${dir}/${file}`)
        if (!bytes) throw new Error(`landing export: ${file} is missing`)
        const [rows, cols] = tile.shape
        const per = spec.values_per_cell
        const want = rows * cols * per * TYPES[spec.dtype].BYTES_PER_ELEMENT
        const got = bytes.byteLength
        if (got !== want) throw new Error(`landing export: ${file} has ${got} bytes, expected ${want}`)
        const v = typedFrom(bytes, spec.dtype, order)
        const dst = arrays[name]
        for (let r = 0; r < rows; r++) {
          const from = r * cols * per
          dst.set(v.subarray(from, from + cols * per), ((tile.row0 + r) * width + tile.col0) * per)
        }
      }),
    ),
  )
  return { manifest, width, height, cellM, origin, arrays }
}

// The window cell holding (x, y) in site metres, or null outside the window (manifest layout).
export function cellOfXY(g, x, y) {
  const col = Math.floor((x - g.origin[0]) / g.cellM)
  const row = g.height - 1 - Math.floor((y - g.origin[1]) / g.cellM)
  if (!(col >= 0 && row >= 0 && col < g.width && row < g.height)) return null
  return { row, col, i: row * g.width + col }
}

// Centre of a window cell in site metres.
export function xyOfCell(g, row, col) {
  return [g.origin[0] + (col + 0.5) * g.cellM, g.origin[1] + (g.height - row - 0.5) * g.cellM]
}

// The cost object the route-finder, missions and HUD read. Rates and blocked cells come from
// routing (time_rate, risk_rate, mask); dem, slope and hazard are only for charts and the readout.
// terrain: { dem, slope, hazard, width, height } from useTerrain, or null.
export function costFromLanding(g, terrain = null) {
  if (terrain && (terrain.width !== g.width || terrain.height !== g.height)) {
    throw new Error(`landing export window is ${g.width} x ${g.height} cells but the site grid is ${terrain.width} x ${terrain.height}: the app expects the window to be the whole site`)
  }
  const { mask, time_rate: timeRate, risk_rate: riskRate } = g.arrays
  const n = g.width * g.height
  const blocked = new Uint8Array(n)
  for (let i = 0; i < n; i++) blocked[i] = mask[i] !== 0 ? 1 : 0
  return {
    width: g.width,
    height: g.height,
    cellM: g.cellM,
    origin: g.origin,
    mask,
    blocked,
    timeRate,
    riskRate,
    dem: terrain?.dem ?? null,
    slope: terrain?.slope ?? null,
    hazard: terrain?.hazard ?? null,
    budget: g.manifest.budget,
    // Red-zone escape (lib/escape.js): only when routing exports these grids; null until then.
    escapeTimeRate: g.arrays.escape_time_rate ?? null,
    escapeRiskRate: g.arrays.escape_risk_rate ?? null,
    escape: g.manifest.escape ?? null,
    maskCodes: g.manifest.mask_codes,
    searches: new Map(),
  }
}

// In the browser: fetch from the site root (vite serves data/out there).
export function loadLandingFromSite() {
  return loadLanding(
    async (p) => {
      const r = await fetch(`./${p}`)
      if (!r.ok) throw new Error(`Could not load ${p} (${r.status})`)
      return r.json()
    },
    async (p) => {
      const r = await fetch(`./${p}`)
      return r.ok ? r.arrayBuffer() : null
    },
  )
}
