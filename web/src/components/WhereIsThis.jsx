import { PLACES, distanceBearing, xyToLatLon, fmtLat, fmtLon } from '../lib/geo.js'
import Tag from './Tag.jsx'

const KM_PER_DEG = (3396190 * Math.PI) / 180 / 1000 // Mars: about 59.27 km per degree of latitude
const DIRS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

// Where the 2 km square sits in Jezero crater, and how far it is to Perseverance's landing site.
// Left: the whole crater. Right: an 8 km close-up with the square and the landing site.
export default function WhereIsThis({ site }) {
  if (!Number.isFinite(site.center_lat) || !Number.isFinite(site.center_lon_east)) return null
  const centre = { lat: site.center_lat, lon: site.center_lon_east }
  const { jezero, landing } = PLACES
  const km = (p, o) => ({ x: (p.lon - o.lon) * Math.cos((o.lat * Math.PI) / 180) * KM_PER_DEG, y: (p.lat - o.lat) * KM_PER_DEG })
  const toLand = distanceBearing(centre, landing)
  const dir = DIRS[Math.round(toLand.bearingDeg / 22.5) % 16]

  // Crater overview: 1 km = 2.6 px.
  const S1 = 2.6
  const c1 = { x: 66, y: 66 }
  const sq = km(centre, jezero)
  const ld = km(landing, jezero)
  const sideKm = site.extent_m[0] / 1000

  // Close-up: 8 km wide, centred between the square and the landing site, 1 km = 16 px.
  const S2 = 16
  const mid = { lat: (centre.lat + landing.lat) / 2, lon: (centre.lon + landing.lon) / 2 }
  const c2 = { x: 205, y: 66 }
  const p2 = (p) => {
    const k = km(p, mid)
    return { x: c2.x + k.x * S2, y: c2.y - k.y * S2 }
  }
  const sq2 = p2(centre)
  const ld2 = p2(landing)
  const corners = [xyToLatLon(0, 0, site), xyToLatLon(site.extent_m[0], site.extent_m[1], site)]

  return (
    <section>
      <h2>Where is this?</h2>
      <svg viewBox="0 0 280 140" className="inset" role="img" aria-label={`The site is in Jezero crater, ${(toLand.distanceM / 1000).toFixed(1)} km ${dir} of Perseverance's landing site`}>
        <circle cx={c1.x} cy={c1.y} r={(jezero.diameterKm / 2) * S1} className="crater" />
        <rect x={c1.x + sq.x * S1 - 3} y={c1.y - sq.y * S1 - 3} width="6" height="6" className="site" />
        <circle cx={c1.x + ld.x * S1} cy={c1.y - ld.y * S1} r="2.2" className="landing" />
        <text x={c1.x} y={c1.y + 3} textAnchor="middle" className="tick">Jezero</text>
        <text x={c1.x} y="136" textAnchor="middle" className="tick">{jezero.diameterKm} km wide</text>

        <rect x={c2.x - 64} y={c2.y - 64} width="128" height="128" className="zoom" />
        <rect x={sq2.x - (sideKm * S2) / 2} y={sq2.y - (sideKm * S2) / 2} width={sideKm * S2} height={sideKm * S2} className="site" />
        <line x1={sq2.x} y1={sq2.y} x2={ld2.x} y2={ld2.y} className="to-landing" />
        <circle cx={ld2.x} cy={ld2.y} r="4" className="landing" />
        <text x={sq2.x} y={sq2.y + (sideKm * S2) / 2 + 10} textAnchor="middle" className="tick">our site</text>
        <text x={ld2.x} y={ld2.y + 13} textAnchor="middle" className="tick">landing</text>
        <line x1={c2.x - 56} y1={c2.y + 56} x2={c2.x - 56 + S2} y2={c2.y + 56} className="scale" />
        <text x={c2.x - 56} y={c2.y + 52} className="tick">1 km</text>
        <text x={c2.x + 58} y={c2.y - 54} textAnchor="end" className="tick">N ↑</text>
      </svg>
      <p className="muted">
        Centre {fmtLat(centre.lat)}, {fmtLon(centre.lon)}; the square runs {fmtLat(corners[0].lat)} to {fmtLat(corners[1].lat)} and {fmtLon(corners[0].lon)} to{' '}
        {fmtLon(corners[1].lon)} <Tag kind="assumption" title="Site centre chosen by eye by the team on the USGS HiRISE terrain mosaic (data/site.json), not a published coordinate" />
      </p>
      <p className="muted">
        Perseverance landed at {landing.name.split(' (')[0]}, <b>{(toLand.distanceM / 1000).toFixed(1)} km {dir}</b> of the site centre (bearing {Math.round(toLand.bearingDeg)}°){' '}
        <Tag kind="real" title={`${landing.source}: ${fmtLat(landing.lat)}, ${fmtLon(landing.lon)}. Jezero: ${jezero.source}`} />
      </p>
    </section>
  )
}
