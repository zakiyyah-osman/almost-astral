// Checks a route against the hazard image (CONTRACT.md: one pixel per cell, row 0 is north).
// Pure maths on pixel data, so it runs in the browser and in tests.
// hazard.png draws red (do not enter) and yellow (careful); green cells are see-through.

export function classifyPixel(r, g, alpha) {
  if (alpha === 0) return 'safe'
  if (r > 180 && g < 110) return 'red'
  if (r > 200 && g > 150) return 'yellow'
  return 'safe'
}

function lines(route) {
  const out = []
  const geoms = route?.type === 'FeatureCollection' ? route.features.map((f) => f.geometry) : [route?.geometry ?? route]
  for (const g of geoms) {
    if (g?.type === 'LineString') out.push(g.coordinates)
    else if (g?.type === 'MultiLineString') out.push(...g.coordinates)
  }
  return out.map((l) => l.filter((c) => Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1])))
}

// image: { data, width, height } like canvas ImageData. extent: [width_m, height_m].
// Returns metres of route over each class, or null when there is nothing to check.
export function checkRoute(route, image, extent, stepM = 2) {
  if (!image?.data || !image.width || !image.height || !extent) return null
  const [w, h] = extent
  const total = { safe: 0, yellow: 0, red: 0 }
  let any = false
  for (const line of lines(route)) {
    for (let i = 1; i < line.length; i++) {
      const [x0, y0] = line[i - 1]
      const [x1, y1] = line[i]
      const len = Math.hypot(x1 - x0, y1 - y0)
      if (len === 0) continue
      const n = Math.max(1, Math.ceil(len / stepM))
      for (let k = 0; k < n; k++) {
        const f = (k + 0.5) / n
        const x = x0 + (x1 - x0) * f
        const y = y0 + (y1 - y0) * f
        const col = Math.min(image.width - 1, Math.max(0, Math.floor((x / w) * image.width)))
        const row = Math.min(image.height - 1, Math.max(0, Math.floor(((h - y) / h) * image.height)))
        const p = (row * image.width + col) * 4
        total[classifyPixel(image.data[p], image.data[p + 1], image.data[p + 3])] += len / n
        any = true
      }
    }
  }
  if (!any) return null
  const sum = total.safe + total.yellow + total.red
  return { safeM: total.safe, yellowM: total.yellow, redM: total.red, totalM: sum }
}
