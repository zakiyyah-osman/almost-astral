// The whole-crater grid (data/out/crater/grid.json + height.i16, hazard.u8, slope.u8, from
// python data/build_real.py crater), for the pointer readout and routes outside the 2 km site.
// It runs in a Web Worker (crater.worker.js): parsing 1600 x 1600 cells and searching them must never
// happen on the page's main thread. These are plain functions so they can be tested in Node.
//
// All positions in and out are in the 2 km SITE's metres (x east, y north of its south-west corner),
// like the rest of the app; points outside the site simply have x, y outside 0..2000. Inside, the
// crater grid has its own metres; the two are tied through latitude and longitude (both grids are
// equirectangular on the Mars sphere, see geo.js), so the conversion is exact.
//
// Jobs (state = createCraterState()):
//   load   { header, height, hazard, slope, params, site }   ArrayBuffers in; builds the cost grid
//   probe  { x, y, shelters }   terrain at a point: { inCrater, z, slope, hazard, noData, back }
//          shelters: [{ x, y }] (the route's start, and the destination when it has a shelter);
//          `back` = walking minutes from the point to the nearest shelter (no ingress), null if none
//   plans  { points, ingress, profiles, shelters }   planOuting on the crater grid, results in site metres
import { buildCost, timeField, snapToFree } from './pathfind.js'
import { planOuting } from './outing.js'
import { cellOf, centreOf } from './terrain.js'
import { xyToLatLon, latLonToXY } from './geo.js'
import { radiationModel, doseTotal } from '../hud/sim.js'

export function createCraterState() {
  return { cost: null, frame: null, site: null, header: null, field: null, fieldKey: '', cache: new Map(), doseFor: () => null }
}

// Typed grids from the raw little-endian files described by grid.json.
export function gridsFrom(header, heightBuf, hazardBuf, slopeBuf) {
  const n = header.rows * header.cols
  const h = new Int16Array(heightBuf.slice(0, n * 2))
  const hz = new Uint8Array(hazardBuf.slice(0, n))
  const sl = new Uint8Array(slopeBuf.slice(0, n))
  if (h.length !== n || hz.length !== n || sl.length !== n) throw new Error(`crater grid files do not match grid.json (${header.cols} x ${header.rows})`)
  const dem = new Float32Array(n)
  const slope = new Float32Array(n)
  const hNo = header.height.nodata
  const sNo = header.slope.nodata
  const step = header.slope.scale
  for (let i = 0; i < n; i++) {
    dem[i] = h[i] === hNo ? NaN : h[i]
    slope[i] = sl[i] === sNo || h[i] === hNo ? NaN : sl[i] * step
  }
  return { dem, slope, hazard: hz }
}

// The crater grid as a geo.js "site": metres from its south-west corner, centred on its centre.
const frameOf = (header) => ({
  extent_m: [header.cols * header.cell_m, header.rows * header.cell_m],
  center_lat: header.projection.center_lat,
  center_lon_east: header.projection.center_lon_east,
})

const toCrater = (state, p) => {
  const ll = xyToLatLon(p.x, p.y, state.site)
  return latLonToXY(ll.lat, ll.lon, state.frame)
}
const toSite = (state, x, y) => {
  const ll = xyToLatLon(x, y, state.frame)
  return latLonToXY(ll.lat, ll.lon, state.site)
}

const fieldKeyOf = (shelters) => (shelters ?? []).map((p) => `${Math.round(p.x)},${Math.round(p.y)}`).join('|')

// Minutes to the nearest shelter from every cell, kept while the shelters stay the same.
function ensureField(state, shelters) {
  const key = fieldKeyOf(shelters)
  if (key === state.fieldKey) return state.field
  const { cost } = state
  const cells = (shelters ?? [])
    .map((p) => {
      const q = toCrater(state, p)
      return snapToFree(cost, q.x, q.y)?.i
    })
    .filter((i) => i != null)
  state.field = cells.length ? timeField(cost, cells) : null
  state.fieldKey = key
  return state.field
}

export function runCraterTask(state, type, a) {
  if (type === 'load') {
    const g = gridsFrom(a.header, a.height, a.hazard, a.slope)
    state.header = a.header
    state.frame = frameOf(a.header)
    state.site = a.site
    state.cost = buildCost({ ...g, width: a.header.cols, height: a.header.rows, cellM: a.header.cell_m, params: a.params })
    state.field = null
    state.fieldKey = ''
    state.cache = new Map()
    const model = a.radRows?.length ? radiationModel(a.radRows) : null
    state.doseFor = model ? (min) => doseTotal(model, min, null) : (min) => (min / 60) * (a.backgroundUsvH ?? 0)
    return { rows: a.header.rows, cols: a.header.cols, cellM: a.header.cell_m, bounds: a.header.bounds_latlon }
  }
  const { cost } = state
  if (!cost) throw new Error('crater grid not loaded yet')
  if (type === 'probe') {
    const q = toCrater(state, a)
    const c = cellOf(q.x, q.y, cost.width, cost.height, cost.cellM)
    if (!c) return { inCrater: false }
    const z = cost.dem[c.i]
    if (!Number.isFinite(z)) return { inCrater: true, noData: true }
    const here = { inCrater: true, z, slope: cost.slope[c.i], hazard: cost.hazard[c.i] }
    // lazyBack: answer the terrain now and leave the minutes-back field (seconds on the whole crater)
    // for the worker to work out right after this answer has gone (job 'field').
    if (a.lazyBack && fieldKeyOf(a.shelters) !== state.fieldKey) {
      state.wantShelters = a.shelters
      return { ...here, back: null, backPending: true }
    }
    const field = ensureField(state, a.shelters)
    return { ...here, back: field && Number.isFinite(field[c.i]) ? field[c.i] : null }
  }
  if (type === 'field') {
    ensureField(state, a.shelters)
    return true
  }
  if (type === 'plans') {
    const field = ensureField(state, a.shelters)
    const pts = a.points.map((p) => ({ ...p, ...toCrater(state, p) }))
    const out = {}
    for (const { id, w } of a.profiles) {
      const r = planOuting(cost, pts, w, cost.params, { ingress: a.ingress, doseFor: state.doseFor, cache: state.cache, profile: id })
      if (!r.ok) {
        out[id] = { ok: false, reason: r.reason, from: r.from && a.points.find((p) => p.id === r.from.id), to: r.to && a.points.find((p) => p.id === r.to.id) }
        continue
      }
      // Back to site metres for drawing, with the minutes back to shelter at every track point.
      const ingressMin = a.ingress ? cost.params.ingress_min : 0
      r.track = r.track.map((p) => {
        const s = toSite(state, p.x, p.y)
        const backMin = field && Number.isFinite(field[p.i]) ? field[p.i] + ingressMin : null
        return { ...p, x: s.x, y: s.y, back: backMin, crater: true }
      })
      r.route.features[0].geometry.coordinates = r.route.features[0].geometry.coordinates.map(([x, y]) => {
        const s = toSite(state, x, y)
        return [s.x, s.y]
      })
      const backs = r.track.map((p) => p.back).filter(Number.isFinite)
      r.furthest = backs.length ? Math.max(...backs) : null
      r.grid = 'crater'
      out[id] = r
    }
    return out
  }
  throw new Error(`crater worker: unknown job ${type}`)
}

// Exposed for tests: the centre of a crater cell in site metres.
export function craterCellToSite(state, i) {
  const [x, y] = centreOf(i, state.cost.width, state.cost.height, state.cost.cellM)
  return toSite(state, x, y)
}
