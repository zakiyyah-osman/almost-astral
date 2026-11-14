// Ground photos: real Perseverance raw images with the rover's position when each was taken
// (data/out/photos.geojson, built from NASA's raw image API and the published traverse waypoints).
//
// For the path system (no React, no Leaflet, all positions in degrees: lat north, lon east):
//
//   setPhotos(featureCollection)   loadData.js calls this once with photos.geojson. Until then the
//                                  helpers see no photos and return null / [].
//
//   nearestPhoto(lat, lon) -> { photo, distance_m } | null
//       The closest photo to a point, e.g. the destination the user picked. Show it with
//       describeNearest(result): "Taken 120 m from here" when close, and otherwise the text
//       "No ground photos here: the nearest is 1.4 km away" instead of the photo. Never present a
//       far-away photo as the destination.
//
//   photosAlongPath(path, maxDist = 100) -> [{ photo, distance_m, along_m }]
//       Photos within maxDist metres of a path, in the order you meet them walking it: for a
//       "preview your walk" strip. path is a list of points, each { lat, lon } or [lon, lat]
//       (GeoJSON order). distance_m is how far the photo is from the path, along_m how far along
//       the path it is. Empty list when no photo is that close.
//
//   photo = { file, url, sol, camera, image_id, date_utc, credit, lat, lon, position_source }
//       url is ready for an <img> (./photos/<file>). Always show the credit with the photo.
//
// Distances are on the Mars sphere (radius 3,396,190 m), fine to a metre over a few kilometres.

import { MARS_RADIUS_M } from './geo.js'

const DEG = Math.PI / 180
export const NEAR_ENOUGH_M = 300 // closer than this, a photo may stand for "this place"

let current = []

// Photo records from a photos.geojson FeatureCollection (Point coordinates are [lon, lat]).
export function photosFrom(fc) {
  return (fc?.features ?? [])
    .filter((f) => f?.geometry?.type === 'Point')
    .map((f) => {
      const p = f.properties ?? {}
      const [lon, lat] = f.geometry.coordinates
      return {
        file: p.file,
        url: p.file ? `./photos/${p.file}` : null,
        sol: p.sol,
        camera: p.camera,
        image_id: p.image_id,
        date_utc: p.date_utc,
        credit: p.credit ?? 'NASA/JPL-Caltech',
        lat,
        lon,
        position_source: p.position_source,
      }
    })
}

export function setPhotos(fc) {
  current = photosFrom(fc)
  return current
}

export const getPhotos = () => current

// Local flat metres (east, north) of b relative to a.
function offsetM(a, b) {
  return [(b.lon - a.lon) * DEG * MARS_RADIUS_M * Math.cos(a.lat * DEG), (b.lat - a.lat) * DEG * MARS_RADIUS_M]
}

export function distanceM(a, b) {
  const [dx, dy] = offsetM(a, b)
  return Math.hypot(dx, dy)
}

export function nearestPhoto(lat, lon, photos = current) {
  let best = null
  for (const photo of photos) {
    const d = distanceM({ lat, lon }, photo)
    if (!best || d < best.distance_m) best = { photo, distance_m: d }
  }
  return best
}

const asPoint = (p) => (Array.isArray(p) ? { lon: p[0], lat: p[1] } : p)

export function photosAlongPath(path, maxDist = 100, photos = current) {
  const pts = (path ?? []).map(asPoint)
  if (!pts.length || !photos.length) return []
  const hits = []
  for (const photo of photos) {
    let best = null
    let walked = 0
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i]
      const b = pts[i + 1] ?? a
      // Project the photo onto the segment a-b, in metres around a.
      const [bx, by] = offsetM(a, b)
      const [px, py] = offsetM(a, photo)
      const len2 = bx * bx + by * by
      const t = len2 > 0 ? Math.max(0, Math.min(1, (px * bx + py * by) / len2)) : 0
      const d = Math.hypot(px - t * bx, py - t * by)
      if (!best || d < best.distance_m) best = { photo, distance_m: d, along_m: walked + t * Math.sqrt(len2) }
      walked += Math.sqrt(len2)
      if (i + 1 >= pts.length) break
    }
    if (best && best.distance_m <= maxDist) hits.push(best)
  }
  return hits.sort((a, b) => a.along_m - b.along_m)
}

const fmtDistance = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m / 10) * 10} m`)

// What to show for a nearestPhoto result: { show, text }. show is false when the photo is too far
// away to stand for the place; then text says so and the photo should not be shown as this place.
export function describeNearest(result, nearEnough = NEAR_ENOUGH_M) {
  if (!result) return { show: false, text: 'No ground photos available.' }
  const { photo, distance_m: d } = result
  if (d > nearEnough) return { show: false, text: `No ground photos here: the nearest is ${fmtDistance(d)} away.` }
  return { show: true, text: `Taken ${fmtDistance(d)} from here by Perseverance (${photo.camera}, sol ${photo.sol}). Credit: ${photo.credit}.` }
}
