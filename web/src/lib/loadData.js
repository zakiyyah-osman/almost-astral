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
  return { ...index, route, waypoints, plan }
}
