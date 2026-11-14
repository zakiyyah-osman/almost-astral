// Loads everything the app needs from data/out (see CONTRACT.md).
// layers.json is required; the route, waypoints and plan are optional so the
// app still runs while another person has not handed their file over yet.

import { setPhotos } from './photos.js'
import { RESEARCH } from './research.js'
import tracedMinerals from '../assets/minerals_12km.png'

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
  // The 12 km mineral research (lib/research.js). The CRISM colour layer from the data lead wins when it
  // is in data/out (a missing file comes back as the HTML page); until then, the areas traced from the
  // research note's map (web/scripts/digitize_minerals_12km.py).
  const realMap = await fetch(`./${RESEARCH.mapFile}`, { method: 'HEAD' })
    .then((r) => r.ok && (r.headers.get('content-type') ?? '').startsWith('image/'))
    .catch(() => false)
  // One "Minerals" layer: the site's own CRISM cells (minerals.png) and the 12 km research areas share
  // its switch, its opacity and its list of minerals (SiteMap.jsx, App.jsx).
  const research = index.site?.center_lat != null
    ? { url: realMap ? `./${RESEARCH.mapFile}` : tracedMinerals, traced: !realMap,
        source: `12 km square around the site: ${RESEARCH.title} (${RESEARCH.author}, ${RESEARCH.date}). ${RESEARCH.caption}${realMap ? '' : ` ${RESEARCH.traced}`}` }
    : null
  let siteLayers = index.layers
  if (research) {
    const has = siteLayers.some((l) => l.id === 'minerals')
    siteLayers = has
      ? siteLayers.map((l) => (l.id === 'minerals' ? { ...l, research, source: `2 km site: ${l.source}. ${research.source}` } : l))
      : [...siteLayers, { id: 'minerals', title: 'Minerals', file: null, default: false, opacity: 0.85, research, source: research.source }]
  }
  return { ...index, layers: [...siteLayers, ...craterLayers, ...photoLayers], route, waypoints, plan, photos }
}
