import { useEffect, useMemo, useState } from 'react'
import { readDem } from './profile.js'
import { slopeDeg, hazardFromSlope, hazardFromImage } from './terrain.js'
import { paramsFrom } from './pathfind.js'
import { classifyPixel } from './routeCheck.js'

// Loads the terrain grids the charts and the point readout need: heights (dem.tif), thermal
// inertia values (thermal_inertia.tif), and the hazard and mineral images as pixels. Route finding
// does not use these: its cost surface is routing's export (landingData.js).
// While the hazard layer is still marked FAKE, routes use hazards from the real slope instead
// (the limits in terrain/thresholds.toml), so a made-up map never steers the crew.

async function buffer(path) {
  const r = await fetch(`./${path}`)
  if (!r.ok) return null
  const b = await r.arrayBuffer()
  // A dev server answers a missing file with the page itself: that is not a TIFF.
  const head = new Uint8Array(b.slice(0, 2))
  return head[0] === 0x49 || head[0] === 0x4d ? b : null
}

function pixels(path) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        ctx.drawImage(img, 0, 0)
        resolve(ctx.getImageData(0, 0, canvas.width, canvas.height))
      } catch {
        resolve(null)
      }
    }
    img.onerror = () => resolve(null)
    img.src = `./${path}`
  })
}

export function useTerrain(data) {
  const [raw, setRaw] = useState({ status: 'loading' })

  useEffect(() => {
    if (!data) return
    let live = true
    const hazardLayer = data.layers.find((l) => l.id === 'hazard')
    const mineralLayer = data.layers.find((l) => l.id === 'minerals')
    Promise.all([
      buffer('dem.tif').catch(() => null),
      buffer('thermal_inertia.tif').catch(() => null),
      hazardLayer && !hazardLayer.source.startsWith('FAKE') ? pixels(hazardLayer.file) : Promise.resolve(null),
      mineralLayer ? pixels(mineralLayer.file) : Promise.resolve(null),
    ]).then(([demBuf, tiBuf, hazardImg, mineralImg]) => {
      if (!live) return
      const dem = demBuf && readDem(demBuf)
      if (!dem) return setRaw({ status: 'missing' })
      const ti = tiBuf && readDem(tiBuf)
      setRaw({ status: 'ready', dem, ti: ti && ti.width === dem.width ? ti : null, hazardImg, mineralImg })
    })
    return () => {
      live = false
    }
  }, [data])

  return useMemo(() => {
    if (raw.status !== 'ready') return { status: raw.status }
    const { dem, ti, hazardImg, mineralImg } = raw
    const { width, height } = dem
    const cellM = data.site.grid?.cell_m ?? data.site.extent_m[0] / width
    const params = paramsFrom(data.plan)
    const slope = slopeDeg(dem.data, width, height, cellM)
    const fromImage = !!hazardImg
    const hazard = fromImage ? hazardFromImage(hazardImg, width, height, classifyPixel) : hazardFromSlope(slope, 10, params.slope_max_deg)
    const grids = { dem: dem.data, slope, hazard, width, height, cellM }
    const hazardSource = fromImage
      ? data.layers.find((l) => l.id === 'hazard')?.source
      : 'Interim, from real slope only: careful over 10°, no-go over 20° (terrain/thresholds.toml), on the HiRISE terrain model. The hazard layer is still fake. Rocks and loose sand are not included yet.'
    const mineralLegend = data.layers.find((l) => l.id === 'minerals')?.legend ?? []
    const hazardLayer = fromImage ? null : { id: 'hazard_slope', title: 'Hazards from real slope (interim)', url: hazardImage(hazard, width, height), source: hazardSource, opacity: 0.7 }
    return { status: 'ready', grids, params, ti, mineralImg, mineralLegend, hazardSource, hazardInterim: !fromImage, hazardLayer }
  }, [raw, data])
}

// The hazard classes as a see-through picture, coloured like hazard.png (CONTRACT.md).
function hazardImage(hazard, width, height) {
  if (typeof document === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  const img = ctx.createImageData(width, height)
  const colour = [null, [240, 190, 40, 150], [220, 50, 50, 190]]
  for (let i = 0; i < hazard.length; i++) {
    const c = colour[hazard[i]]
    if (c) img.data.set(c, i * 4)
  }
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL('image/png')
}

// The mineral at a cell from minerals.png: the legend entry with the nearest colour, or null.
export function mineralAt(img, legend, row, col, width, height) {
  if (!img || !legend?.length) return null
  const pr = Math.min(img.height - 1, Math.floor(((row + 0.5) / height) * img.height))
  const pc = Math.min(img.width - 1, Math.floor(((col + 0.5) / width) * img.width))
  const p = (pr * img.width + pc) * 4
  if (img.data[p + 3] === 0) return null
  const hex = (h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16))
  let best = null
  for (const e of legend) {
    const [r, g, b] = hex(e.color)
    const d = (r - img.data[p]) ** 2 + (g - img.data[p + 1]) ** 2 + (b - img.data[p + 2]) ** 2
    if (!best || d < best.d) best = { d, label: e.label }
  }
  return best && best.d < 60 ** 2 ? best.label : null
}
