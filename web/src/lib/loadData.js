// Loads everything the app needs from data/out (see CONTRACT.md).
// layers.json is required; the route, waypoints and plan are optional so the
// app still runs while another person has not handed their file over yet.

import { setPhotos } from './photos.js'
import { RESEARCH } from './research.js'

async function getJson(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`Could not load ${path} (${res.status})`)
  return res.json()
}

const optional = (path) => (path ? getJson(`./${path}`).catch(() => null) : Promise.resolve(null))

export async function loadData() {
  const index = await getJson('./layers.json')
  const [route, waypoints, plan] = await Promise.all([
    optional(index.vectors?.route),
    optional(index.vectors?.waypoints),
    optional(index.plan),
  ])
  // Whole-crater layers (layers.json "crater", from data/build_real.py crater) join the layer list,
  // so they get the same switches and opacity sliders; scope and bounds tell the map where they go.
  const crater = index.crater
  const craterLayers = (crater?.layers ?? []).map((l) => ({ ...l, scope: 'crater', bounds: crater.bounds_latlon }))

  // Ground photos (vectors.photos): handed to lib/photos.js for nearestPhoto / photosAlongPath, and
  // listed as a switchable layer of camera pins.
  const photosFc = await optional(index.vectors?.photos)
  const photos = setPhotos(photosFc)
  const photoLayers = photos.length
    ? [{ id: 'photos', title: `Ground photos (${photos.length}, Perseverance)`, scope: 'photos', default: true, opacity: 1,
         source: index.sources_notes?.[index.vectors.photos] ?? 'NASA/JPL-Caltech, Perseverance raw images' }]
    : []
  // The 12 km mineral research (lib/research.js): rover sample stars always, and the CRISM colour
  // layer once the data lead has put it in data/out (a missing file comes back as the HTML page).
  const researchMap = await fetch(`./${RESEARCH.mapFile}`, { method: 'HEAD' })
    .then((r) => (r.ok && (r.headers.get('content-type') ?? '').startsWith('image/') ? RESEARCH.mapFile : null))
    .catch(() => null)
  const researchLayers = index.site?.center_lat != null
    ? [{ id: 'research', title: 'Minerals and rover samples (12 km)', scope: 'research', default: true, opacity: 0.75, file: researchMap,
         source: `${RESEARCH.title} (${RESEARCH.author}, ${RESEARCH.date}). ${RESEARCH.caption}` }]
    : []
  return { ...index, layers: [...index.layers, ...craterLayers, ...photoLayers, ...researchLayers], route, waypoints, plan, photos }
}
