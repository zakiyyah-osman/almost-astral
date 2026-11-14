// Grids derived from the terrain model, in the CONTRACT.md layout: row 0 is the north edge,
// index = row * width + col, cell size cell_m metres.

// Slope in degrees at each cell, like numpy.gradient: central differences inside the grid,
// one-sided differences on the edges. A cell next to a missing height gets NaN.
// This is the same formula as routing/grid.py slope_deg, so the app and the planner agree.
export function slopeDeg(dem, width, height, cellM) {
  const out = new Float32Array(width * height)
  const z = (r, c) => dem[r * width + c]
  for (let r = 0; r < height; r++) {
    for (let c = 0; c < width; c++) {
      const c0 = c === 0 ? c : c - 1
      const c1 = c === width - 1 ? c : c + 1
      const r0 = r === 0 ? r : r - 1
      const r1 = r === height - 1 ? r : r + 1
      const dzdx = (z(r, c1) - z(r, c0)) / ((c1 - c0) * cellM)
      const dzdy = (z(r1, c) - z(r0, c)) / ((r1 - r0) * cellM)
      const s = (Math.atan(Math.hypot(dzdx, dzdy)) * 180) / Math.PI
      out[r * width + c] = Number.isFinite(s) && Number.isFinite(z(r, c)) ? s : NaN
    }
  }
  return out
}

// Hazard classes from slope alone: 0 fine, 1 careful (over yellowDeg), 2 do not enter (over redDeg or no data).
// Used while the hazard layer is still fake. The limits are the ones in terrain/thresholds.toml.
export function hazardFromSlope(slope, yellowDeg = 10, redDeg = 20) {
  const out = new Uint8Array(slope.length)
  for (let i = 0; i < slope.length; i++) {
    const s = slope[i]
    out[i] = !Number.isFinite(s) || s > redDeg ? 2 : s > yellowDeg ? 1 : 0
  }
  return out
}

// Hazard classes from hazard.png pixels (red = 2, yellow = 1, see-through = 0), resampled to the grid.
export function hazardFromImage(image, width, height, classify) {
  const out = new Uint8Array(width * height)
  for (let r = 0; r < height; r++) {
    for (let c = 0; c < width; c++) {
      const pr = Math.min(image.height - 1, Math.floor(((r + 0.5) / height) * image.height))
      const pc = Math.min(image.width - 1, Math.floor(((c + 0.5) / width) * image.width))
      const p = (pr * image.width + pc) * 4
      const k = classify(image.data[p], image.data[p + 1], image.data[p + 3])
      out[r * width + c] = k === 'red' ? 2 : k === 'yellow' ? 1 : 0
    }
  }
  return out
}

// Grid cell (row, col) holding the point (x east, y north, metres), or null outside the site.
// Same formula as routing's landing manifest (layout.window_cell_of_point), so a point on a cell
// edge lands in the same cell here and in the route-finder: the north edge y = height * cellM is outside.
export function cellOf(x, y, width, height, cellM) {
  const col = Math.floor(x / cellM)
  const row = height - 1 - Math.floor(y / cellM)
  if (col < 0 || row < 0 || col >= width || row >= height) return null
  return { row, col, i: row * width + col }
}

// Centre of a cell in metres.
export function centreOf(i, width, height, cellM) {
  const row = Math.floor(i / width)
  const col = i % width
  return [(col + 0.5) * cellM, (height - row - 0.5) * cellM]
}
