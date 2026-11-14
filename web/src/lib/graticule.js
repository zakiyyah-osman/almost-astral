// Latitude and longitude lines for whatever part of the map is on screen, so coordinates can be
// read anywhere, not only along the route. Uses the same flat approximation around the site centre
// as geo.js, so a line here and a readout from xyToLatLon always agree.
import { xyToLatLon, latLonToXY } from './geo.js'

const STEPS = [0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5]

// view: { x0, x1, y0, y1 } in site metres. Returns { step, decimals, lats: [{ v, y }], lons: [{ v, x }] }.
export function graticule(view, site, target = 4) {
  const a = xyToLatLon(view.x0, view.y0, site)
  const b = xyToLatLon(view.x1, view.y1, site)
  // The shorter side sets the spacing, so it always gets a few lines and the longer side gets more.
  const span = Math.min(Math.abs(b.lat - a.lat), Math.abs(b.lon - a.lon))
  const step = STEPS.find((s) => span / s <= target) ?? STEPS[STEPS.length - 1]
  const decimals = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9))
  const lats = []
  const lons = []
  const lat0 = Math.ceil(Math.min(a.lat, b.lat) / step) * step
  for (let v = lat0; v <= Math.max(a.lat, b.lat) + 1e-12 && lats.length < 60; v += step) lats.push({ v: +v.toFixed(decimals + 2), y: latLonToXY(v, site.center_lon_east, site).y })
  const lon0 = Math.ceil(Math.min(a.lon, b.lon) / step) * step
  for (let v = lon0; v <= Math.max(a.lon, b.lon) + 1e-12 && lons.length < 60; v += step) lons.push({ v: +v.toFixed(decimals + 2), x: latLonToXY(site.center_lat, v, site).x })
  return { step, decimals, lats, lons }
}
