// Loads everything the app needs from data/out (see CONTRACT.md).
// layers.json is required; the route, waypoints and plan are optional so the
// app still runs while another person has not handed their file over yet.

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
  return { ...index, layers: [...index.layers, ...craterLayers], route, waypoints, plan }
}
