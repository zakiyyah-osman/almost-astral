// Between the local site grid (metres east and north of the south-west corner) and Mars
// latitude / longitude (degrees, longitude east 0-360). A local flat approximation around the
// site centre in layers.json, using the Mars radius from the project rules (3,396,190 m); good to metres over 2 km.
export const MARS_RADIUS_M = 3396190
const DEG = Math.PI / 180

export function xyToLatLon(x, y, site) {
  const [w, h] = site.extent_m
  const lat = site.center_lat + ((y - h / 2) / MARS_RADIUS_M) / DEG
  const lon = site.center_lon_east + ((x - w / 2) / (MARS_RADIUS_M * Math.cos(site.center_lat * DEG))) / DEG
  return { lat, lon: ((lon % 360) + 360) % 360 }
}

export function latLonToXY(lat, lon, site) {
  const [w, h] = site.extent_m
  const x = w / 2 + (lon - site.center_lon_east) * DEG * MARS_RADIUS_M * Math.cos(site.center_lat * DEG)
  const y = h / 2 + (lat - site.center_lat) * DEG * MARS_RADIUS_M
  return { x, y }
}

// Distance (m) and bearing (degrees clockwise from north) from one lat/lon to another, on the Mars sphere.
export function distanceBearing(a, b) {
  const p1 = a.lat * DEG
  const p2 = b.lat * DEG
  const dl = (b.lon - a.lon) * DEG
  const dp = p2 - p1
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  const d = 2 * MARS_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)))
  const brg = (Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)) / DEG + 360) % 360
  return { distanceM: d, bearingDeg: brg }
}

export const fmtLat = (v) => `${Math.abs(v).toFixed(4)}°${v >= 0 ? 'N' : 'S'}`
export const fmtLon = (v) => `${v.toFixed(4)}°E`

// Reference places, from NASA/JPL (see the research report). Planetocentric latitude, east longitude.
export const PLACES = {
  landing: { name: 'Octavia E. Butler Landing (Perseverance)', lat: 18.4447, lon: 77.4508, source: 'NASA/JPL, Perseverance landing site' },
  jezero: { name: 'Jezero crater centre', lat: 18.38, lon: 77.58, diameterKm: 45, source: 'NASA: "28-mile-wide (45-kilometer-wide)"; USGS SIM 3464' },
}
