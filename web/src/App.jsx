import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import SiteMap from './components/SiteMap.jsx'
import HudView from './hud/HudView.jsx'
import { loadData } from './lib/loadData.js'
import MissionCard from './components/MissionCard.jsx'
import RouteCharts from './components/RouteCharts.jsx'
import ConditionsPanel from './components/ConditionsPanel.jsx'
import WhereIsThis from './components/WhereIsThis.jsx'
import DataStatus from './components/DataStatus.jsx'
import RoutePlanner from './components/RoutePlanner.jsx'
import ProfileCards from './components/ProfileCards.jsx'
import ModeCompare from './components/ModeCompare.jsx'
import Icon from './components/Icon.jsx'
import Tag from './components/Tag.jsx'
import MineralKey from './components/MineralKey.jsx'
import RoutePhotos from './components/RoutePhotos.jsx'
import RouteNotice from './components/RouteNotice.jsx'
import { routeFailure, unreachableText } from './lib/routeFailure.js'
import { MINERAL_CLASSES } from './lib/research.js'
import { buildTimeline, doseTotal, parseTable, radiationModel } from './hud/sim.js'
import { useTerrain, mineralAt } from './lib/useTerrain.js'
import { useCrater, useCraterProbe, useAsync } from './lib/useCrater.js'
import { waypointsFor } from './lib/outing.js'
import { PROFILES, paramsFrom, reasonText, route as findRoute, searchFrom, timeField } from './lib/pathfind.js'
import { loadLandingFromSite, costFromLanding } from './lib/landingData.js'
import { landingCheck } from './lib/landingCheck.js'
import { escapeAvailable, zoneCodes } from './lib/escape.js'
import { useRoutePlan } from './lib/useRoutePlan.js'
import { unverifiedWarning, planExtras } from './lib/teamOuting.js'
import { detourCosts, bestOrder, mineralTargets } from './lib/mission.js'
import { photoId } from './lib/photos.js'
import { cellOf } from './lib/terrain.js'
import { xyToLatLon, fmtLat, fmtLon } from './lib/geo.js'

// hazard.png draws red and yellow; green cells are see-through, so green here just means "no overlay".
const HAZARD_KEY = [
  ['var(--ok)', 'Fine to walk'],
  ['#f0be28', 'Careful'],
  ['#dc3232', 'Do not enter'],
]
// thermal.png colour stops, from data/adapters/themis.py (fixed scale 50 to 800 so maps compare).
const THERMAL_RAMP = 'linear-gradient(90deg, rgb(40,50,120), rgb(200,170,110), rgb(230,120,40), rgb(255,245,230))'

// One-click sets of layers: the ones that exist in layers.json are switched on, the rest off.
// 'base' stands for the real HiRISE image when there is one, and the shaded relief otherwise.
const PRESETS = [
  { id: 'safety', label: 'Safety', hint: 'Hazards on terrain', on: ['base', 'hazard'] },
  { id: 'science', label: 'Science', hint: 'Minerals on terrain', on: ['base', 'minerals'] },
  { id: 'ground', label: 'Ground', hint: 'Slope and thermal', on: ['base', 'slope', 'thermal'] },
]
const presetIds = (preset, ids) =>
  preset.on.map((id) => (id === 'base' ? (ids.includes('hirise') ? 'hirise' : 'relief') : id === 'hazard' && ids.includes('hazard_slope') ? 'hazard_slope' : id))
const HAZ_WORD = ['fine', 'careful', 'no-go']
const BACKGROUND_USV_H = 640 / 24 // routing/config.toml: 0.64 mSv/day (Curiosity RAD at Gale), used only if radiation.csv is missing
const TABS = [
  ['route', 'Route'],
  ['compare', 'Compare'],
  ['layers', 'Layers'],
  ['site', 'Site'],
]
const SIDEBAR = { min: 280, max: 720, start: 360, snapShut: 200 }
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
// One trip per mode, kept when switching: start (the landing in My trip), side quests, destination, profile.
// One way, as routing plans it. Team outing with no start shows routing's plan.json demo route.
const EMPTY_TRIP = { start: null, quests: [], dest: null, profile: 'balanced' }
// A route with a point outside the 2 km site: never to be read as one of the planner's site routes.
const CRATER_LABEL = 'Exploratory: 40 m crater grid, computed in the browser'


// Browser storage can be missing or blocked (private windows, previews): never let that break the page.
const stored = (key, fallback) => {
  try {
    const v = window.localStorage.getItem(key)
    return v == null ? fallback : JSON.parse(v)
  } catch {
    return fallback
  }
}
const store = (key, value) => {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* not saved: fine */
  }
}

// focusPhoto: a ground photo id from #map?photo=<id> (main.jsx): the map opens on that photo.
export default function App({ focusPhoto = null }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [layerState, setLayerState] = useState({})
  const [view, setView] = useState('planning')
  const [tab, setTab] = useState('route')
  const [selectedStop, setSelectedStop] = useState(null)
  const [astronaut, setAstronaut] = useState(null) // set by the HUD while it simulates
  const [large, setLarge] = useState(false) // big text for a projector
  const [visorOn, setVisor] = useState(false) // full-screen visor view
  const [openSource, setOpenSource] = useState({}) // layers whose source line is expanded
  const [mode, setMode] = useState('outing') // 'outing' (Team outing) | 'mission' (My trip): the same planner, one trip each
  const [trips, setTrips] = useState({ outing: EMPTY_TRIP, mission: EMPTY_TRIP })
  const [demoOff, setDemoOff] = useState(false) // Clear route in Team outing also hides routing's demo route
  const [startNote, setStartNote] = useState(null) // Team outing: why the last start click was refused
  const trip = trips[mode]
  const setTrip = useCallback((fn) => setTrips((ts) => ({ ...ts, [mode]: typeof fn === 'function' ? fn(ts[mode]) : fn })), [mode])
  const profile = trip.profile
  const setProfile = (id) => setTrip((t) => ({ ...t, profile: id }))
  const [picking, setPicking] = useState(null) // 'landing' | 'quest' | 'dest' while waiting for a map click
  const [landingInfo, setLandingInfo] = useState(null) // routing's landing check of the last landing click (lib/landingCheck.js)
  const [notice, setNotice] = useState(null) // a pop-up (moved landing, no route) until dismissed: { title, messages, footer }
  const [hover, setHover] = useState(null)
  const [inspect, setInspect] = useState(null) // a clicked point, kept until closed
  const [centre, setCentre] = useState(null)
  const [probe, setProbe] = useState(null)
  const [radRows, setRadRows] = useState(null)
  const [gridOn, setGridOn] = useState(true)
  const [targetsOn, setTargetsOn] = useState(true)
  const [sideW, setSideW] = useState(() => stored('aa.sidebarW', SIDEBAR.start))
  const [sideShut, setSideShut] = useState(() => stored('aa.sidebarShut', false))
  const [dragging, setDragging] = useState(false)
  const [copied, setCopied] = useState(false)
  const [mineralsShown, setMineralsShown] = useState([]) // minerals switched on in the Minerals card; none until picked
  const visor = visorOn && view === 'hud'

  // Opened from a photo link (#map?photo=<id>): main.jsx has passed the id on as focusPhoto, so trim
  // the hash back to #map. Then a reload or the Home button behave as for a plain #map.
  useEffect(() => {
    if (window.location.hash.startsWith('#map?')) window.history.replaceState(window.history.state, '', '#map')
  }, [])

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        const ids = d.layers.map((l) => l.id)
        const start = presetIds(PRESETS[0], ids) // open on the Safety view
        // Crater-wide layers and photo pins start from their own default; the site layers from the Safety preset.
        // Opened on a photo (#map?photo=<id>): the photo pins are on, so its pin shows.
        const showPhoto = !!focusPhoto && (d.photos ?? []).some((p) => photoId(p) === focusPhoto)
        setLayerState(Object.fromEntries(d.layers.map((l) => [l.id, { on: (showPhoto && l.scope === 'photos') || (l.scope ? !!l.default : start.includes(l.id)), opacity: l.opacity ?? 1 }])))
        if (d.tables?.radiation) {
          fetch(`./${d.tables.radiation}`)
            .then((r) => (r.ok ? r.text() : ''))
            .then((t) => setRadRows(parseTable(t)))
            .catch(() => setRadRows([]))
        }
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => store('aa.sidebarW', sideW), [sideW])
  useEffect(() => store('aa.sidebarShut', sideShut), [sideShut])

  // Esc stops picking, then closes the inspected point.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      if (picking) setPicking(null)
      else setInspect(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picking])

  // Routing's landing export (data/out/landing): the cost surface every route is searched on.
  const [landingGrid, setLandingGrid] = useState(null)
  const [landingError, setLandingError] = useState(null)
  useEffect(() => {
    loadLandingFromSite()
      .then(setLandingGrid)
      .catch((e) => setLandingError(e.message))
  }, [])
  const terrain = useTerrain(data)
  const costState = useMemo(() => {
    if (!landingGrid || terrain.status !== 'ready') return { cost: null, error: null }
    try {
      return { cost: costFromLanding(landingGrid, terrain.grids), error: null }
    } catch (e) {
      return { cost: null, error: e.message }
    }
  }, [landingGrid, terrain])
  const cost = costState.cost
  const routeError = landingError ?? costState.error
  const ready = !!cost
  const params = useMemo(() => (data && landingGrid ? paramsFrom(data.plan, landingGrid.manifest) : terrain.params), [data, landingGrid, terrain.params])
  const legCache = useMemo(() => new Map(), [cost]) // legs already searched on this terrain

  const features = data?.waypoints?.features ?? []
  const stops = features.filter((f) => f.properties.kind === 'stop')
  const asPoint = (f) => ({ id: f.properties.id, name: f.properties.name, kind: f.properties.kind, x: f.geometry.coordinates[0], y: f.geometry.coordinates[1], why: f.properties.why, photo: f.properties.photo, extra: f.properties })

  // While the hazard layer is fake, show the interim hazards from the real slope in its place.
  // Routing's landing zones (landing/landing_zones.png): safe and marginal landing cells, placed
  // with the manifest's zones_png origin and extent (the same grid as hazard.png).
  const zonesLayer = useMemo(() => {
    const z = landingGrid?.manifest?.zones_png
    if (!z) return null
    const m = landingGrid.manifest
    const t = m.thresholds
    const rules = `pad radius ${t.pad_radius_m.value} m, tilt at most ${t.max_pad_slope_deg.value}°, height range at most ${t.max_height_range_m.value} m, roughness at most ${t.max_roughness_m.value} m, clearance at least ${t.hazard_clearance_m.value} m; marginal within ${t.marginal_pct.value}% of a limit`
    return {
      id: 'landing_zones',
      title: 'Landing zones',
      url: `./landing/${z.file}`,
      boundsXY: [z.origin_m, [z.origin_m[0] + z.extent_m[0], z.origin_m[1] + z.extent_m[1]]],
      opacity: 0.6,
      legend: z.legend.map((e) => ({ code: e.code, label: e.code === 0 ? 'Safe to land' : e.code === 1 ? 'Marginal' : e.label, color: `rgba(${e.rgba[0]}, ${e.rgba[1]}, ${e.rgba[2]}, ${(e.rgba[3] / 255).toFixed(2)})` })),
      source: `Calculated by routing/export_landing.py from the HiRISE terrain model and the hazard map: ${rules}. All limits are team assumptions pending Nahla (routing/config.toml [landing]).`,
    }
  }, [landingGrid])
  const extraLayers = useMemo(() => [terrain.hazardLayer, zonesLayer].filter(Boolean), [terrain.hazardLayer, zonesLayer])
  // The landing zones start off, and switch on whenever a landing site is being chosen.
  useEffect(() => {
    if (!zonesLayer) return
    setLayerState((st) => (st.landing_zones ? st : { ...st, landing_zones: { on: false, opacity: zonesLayer.opacity } }))
  }, [zonesLayer])
  useEffect(() => {
    if (picking === 'landing' && zonesLayer) setLayerState((st) => ({ ...st, landing_zones: { opacity: zonesLayer.opacity, ...st.landing_zones, on: true } }))
  }, [picking, zonesLayer])
  useEffect(() => {
    const l = terrain.hazardLayer
    if (!l) return
    setLayerState((st) => (st[l.id] ? st : { ...st, [l.id]: { on: !!st.hazard?.on, opacity: l.opacity }, ...(st.hazard ? { hazard: { ...st.hazard, on: false } } : {}) }))
  }, [terrain.hazardLayer])

  // Named places for the pickers.
  const places = useMemo(() => {
    const out = []
    stops.forEach((f, k) => out.push({ ...asPoint(f), name: `${k + 1} · ${f.properties.name}` }))
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const radModel = useMemo(() => (radRows?.length ? radiationModel(radRows) : null), [radRows])
  const doseFor = useMemo(() => (min) => (radModel ? doseTotal(radModel, min, null) : (min / 60) * BACKGROUND_USV_H), [radModel])

  const planOpts = useMemo(() => ({ ingress: true, doseFor, cache: legCache }), [doseFor, legCache])
  const outing = mode === 'outing'
  // The shared route-planning workflow (lib/useRoutePlan.js), for the active mode's trip.
  const demo = useMemo(() => (data?.plan ? { plan: data.plan, routes: data.routes, waypoints: data.waypoints } : null), [data])
  const rp = useRoutePlan({ cost: ready ? cost : null, params, trip, demo: outing && !demoOff ? demo : null, doseFor, legCache, escape: outing })
  const { isDemo, points, back, shelterCells } = rp
  const ingress = params?.ingress_min ?? 0
  const profInfo = PROFILES.find((p) => p.id === profile)

  // Points inside the 2 km site use the site grid (rp, above). A trip point anywhere else in the crater
  // (the destination or a side quest; the start stays on the site grid) uses the 40 m crater grid, which
  // lives in a Web Worker (lib/crater.worker.js) and is never parsed on the page. Same one-way rule:
  // ingress counted, minutes back to the start.
  const inSite = useCallback((p) => !!(p && cost && cellOf(p.x, p.y, cost.width, cost.height, cost.cellM)), [cost])
  const allInSite = !points || points.every(inSite)
  const hoverOut = !!hover && ready && !inSite(hover)
  const inspectOut = !!inspect && ready && !inSite(inspect)
  const rad = useMemo(() => ({ radRows: radRows ?? [], backgroundUsvH: BACKGROUND_USV_H }), [radRows])
  const crater = useCrater(data, params, rad, hoverOut || inspectOut || !allInSite)
  const home = points?.[0] ?? trip.start
  const shelters = useMemo(() => (home ? [{ x: home.x, y: home.y }] : []), [home?.x, home?.y]) // eslint-disable-line react-hooks/exhaustive-deps
  const hoverProbe = useCraterProbe(crater, hoverOut ? hover : null, shelters)
  const inspectProbe = useCraterProbe(crater, inspectOut ? inspect : null, shelters)
  const craterJob = useAsync(() => {
    if (allInSite || !points || crater.status !== 'ready') return null
    const plain = points.map(({ id, name, kind, x, y, stopMin }) => ({ id, name, kind, x, y, stopMin }))
    return crater.call('plans', { points: plain, ingress: true, shelters, profiles: PROFILES.map((p) => ({ id: p.id, w: params[p.key] })) })
  }, [crater, points, allInSite, shelters, params])
  const craterBusy = !allInSite && (crater.status === 'loading' || craterJob.busy)

  // One route state for the rest of the app: rp on the site grid, else the crater worker's plans.
  // The worker returns a failed plan's reason code only; its text is the landing export's for that code
  // (the crater cost uses the same mask codes, lib/pathfind.js buildCost).
  const craterResults = useMemo(() => {
    const v = craterJob.value
    if (!v || !cost) return v
    return Object.fromEntries(Object.entries(v).map(([id, r]) => [id, r.ok || r.reason_text ? r : { ...r, reason_text: reasonText(cost, r.reason) }]))
  }, [craterJob.value, cost])
  const results = allInSite ? rp.results : craterResults
  const active = results?.[profile]
  const ok = !!active?.ok
  const craterRoute = active?.grid === 'crater'
  const status = allInSite ? rp.status : !results ? (craterBusy ? 'pending' : 'failed') : ok ? 'ok' : 'failed'
  const craterAlt = useMemo(() => (!allInSite && results ? PROFILES.filter((p) => p.id !== profile && results[p.id]?.ok).map((p) => results[p.id].route) : null), [allInSite, results, profile])
  const altRoutes = allInSite ? rp.altRoutes : craterAlt
  // A crater route's track already carries minutes back to the start (worked out in the worker).
  const track = allInSite ? rp.track : ok ? active.track : null
  const furthest = allInSite ? rp.furthest : track ? track.reduce((a, b) => ((b.back ?? -1) > (a.back ?? -1) ? b : a)) : null
  const routeWaypoints = rp.waypoints ?? (points ? waypointsFor(points) : null)
  const craterArrivals = useMemo(() => {
    if (allInSite || !ok || !routeWaypoints) return {}
    const tl = buildTimeline(active.plan, routeWaypoints, active.route)
    return Object.fromEntries((tl?.segments ?? []).filter((s) => s.type === 'walk').map((s) => [s.to, s.t1]))
  }, [allInSite, ok, active, routeWaypoints])
  const arrivals = allInSite ? rp.arrivals : craterArrivals

  // What each side quest adds, on the active mode.
  const detours = useMemo(() => {
    // Site grid only: on the crater grid each detour would need its own long search.
    if (!ready || isDemo || !allInSite || !trip.quests.length || !trip.start || !trip.dest) return null
    return detourCosts(cost, trip, params[profInfo.key], params, planOpts)
  }, [ready, cost, params, isDemo, trip, profInfo, planOpts, allInSite])

  // Mineral areas from CRISM, and roughly how far each is off the active route (there and back).
  const allTargets = useMemo(() => (ready ? mineralTargets(terrain.mineralImg, terrain.mineralLegend, cost, { minCells: 10 }) : []), [ready, terrain, cost])
  const targets = useMemo(() => {
    if (!allTargets.length) return []
    // A crater route's cells are crater cells, not site cells: no detour times for it.
    const cells = ok && !craterRoute ? [...new Set(active.track.map((p) => p.i))] : null
    const field = cells?.length ? timeField(cost, cells) : null
    return allTargets
      .map((t) => ({ ...t, detourMin: field && Number.isFinite(field[t.i]) ? 2 * field[t.i] : null }))
      .sort((a, b) => (a.detourMin ?? 1e9) - (b.detourMin ?? 1e9) || b.areaM2 - a.areaM2)
  }, [allTargets, ok, active, cost, craterRoute])

  // What the rest of the app reads: the active mode's plan, route and waypoints (one route state).
  // No route means nothing drawn and no HUD plan. hudPlan works on the site grid; a crater route goes to
  // the HUD as planned (its own timeline).
  const shown = allInSite
    ? { ...data, plan: rp.plan, route: rp.route, waypoints: rp.waypoints ?? data?.waypoints }
    : { ...data, plan: ok ? active.plan : null, route: ok ? active.route : null, waypoints: routeWaypoints ?? data?.waypoints }
  const hud = allInSite ? rp.hud : ok ? { plan: active.plan, route: active.route, waypoints: routeWaypoints } : null
  const hudData = hud ? { ...data, ...hud } : { ...data, plan: null, route: null }
  const hudKey = isDemo ? 'demo' : ok ? `${mode}-${profile}-${craterRoute ? 'crater-' : ''}${active.route.features[0].geometry.coordinates.length}-${active.plan.totals.total_min}` : 'none'

  // A route that cannot be found also gets a pop-up, once per new failure (lib/routeFailure.js).
  const failure = useMemo(() => routeFailure(active), [active])
  const lastFailure = useRef(null)
  useEffect(() => {
    if (failure && failure.key !== lastFailure.current) setNotice(failure)
    lastFailure.current = failure?.key ?? null
  }, [failure])
  const unverified = isDemo ? unverifiedWarning(data?.plan) : null

  // Pins on the map: the team's stops, and for the demo route its start (plan.json start, "Demo start").
  const mapWaypoints = isDemo ? rp.waypoints : data?.waypoints ?? null

  // The trip's own pins: the Team outing start, numbered side quests, destination (the landing has its own pin).
  const missionPins = useMemo(() => {
    if (isDemo) return null
    const t = (id) => (arrivals[id] != null ? ` · T+${Math.floor(arrivals[id] / 60)}:${String(Math.round(arrivals[id] % 60)).padStart(2, '0')}` : '')
    const out = []
    if (outing && trip.start) out.push({ ...trip.start, label: 'S', kind: 'm-start', title: 'Start' })
    trip.quests.forEach((q, k) => out.push({ ...q, label: String(k + 1), kind: 'quest', title: `${q.name}${t(`q${k + 1}`)}` }))
    if (trip.dest) out.push({ ...trip.dest, label: (trip.dest.name || 'J0').slice(0, 2), kind: 'm-dest', title: `${trip.dest.name || 'Destination'}${t('dest')}` })
    return out
  }, [isDemo, outing, trip, arrivals])

  // The landing pin: green when safe, amber when marginal; a moved landing also marks the click.
  const landingPin = useMemo(() => {
    if (mode !== 'mission' || !trip.start || !landingInfo?.chosen) return null
    const moved = landingInfo.status === 'moved'
    return {
      x: trip.start.x,
      y: trip.start.y,
      status: moved ? 'safe' : landingInfo.status,
      title: moved ? `Landing (moved ${landingInfo.moved_m.toFixed(1)} m to a safe spot)` : landingInfo.messages[0]?.title ?? 'Landing',
      from: moved ? landingInfo.click : null,
    }
  }, [mode, trip.start, landingInfo])

  // Everything known about one point: anywhere on the map, with terrain values where there is data.
  const describe = useCallback(
    (p, probe) => {
      if (!p || !data) return null
      const ll = data.site.center_lat != null ? xyToLatLon(p.x, p.y, data.site) : null
      const out = { x: p.x, y: p.y, ll, inside: false }
      const from = points?.[0]
      if (from) {
        const dx = p.x - from.x
        const dy = p.y - from.y
        out.fromStart = { m: Math.hypot(dx, dy), dir: COMPASS[Math.round(((Math.atan2(dx, dy) * 180) / Math.PI + 360) / 45) % 8], name: from.name }
      }
      if (!ready) return out
      const c = cellOf(p.x, p.y, cost.width, cost.height, cost.cellM)
      if (!c) {
        // Outside the 2 km site: the 40 m crater grid, answered by the crater worker. The latest answer
        // stands for the pointer while it is within a cell or two of the point that was asked about.
        if (!data.crater?.grid_header || crater.status === 'error') return out
        const v = probe && Math.hypot(probe.for.x - p.x, probe.for.y - p.y) < 80 ? probe.value : undefined
        if (v === undefined) return { ...out, pending: true }
        if (!v?.inCrater) return out
        if (v.noData) return { ...out, inside: true, crater: true, noData: true }
        return { ...out, inside: true, crater: true, z: v.z, slope: v.slope, hazard: v.hazard, ti: null, mineral: null, back: v.back != null ? v.back + ingress : null, backPending: !!v.backPending }
      }
      return {
        ...out,
        inside: true,
        z: cost.dem[c.i],
        slope: cost.slope[c.i],
        hazard: cost.hazard[c.i],
        ti: terrain.ti ? terrain.ti.data[c.i] : null,
        mineral: mineralAt(terrain.mineralImg, terrain.mineralLegend, c.row, c.col, cost.width, cost.height),
        // Blocked for walking (routing's mask): buffer and sealed cells look yellow or green on the hazard layer.
        blocked: cost.mask?.[c.i] ? { code: cost.mask[c.i], text: reasonText(cost, cost.mask[c.i]) } : null,
        back: back && Number.isFinite(back[c.i]) ? back[c.i] + ingress : null,
      }
    },
    [data, ready, cost, terrain, back, ingress, points, crater.status],
  )
  const readout = useMemo(() => describe(hover, hoverProbe), [describe, hover, hoverProbe])
  // The clicked point: the same search as the routes, from the point back to the landing (w = 0).
  // On the crater grid the worker's answer stands (its minutes back come from the 40 m field).
  const inspected = useMemo(() => {
    const d = describe(inspect, inspectProbe)
    if (!d?.inside || d.crater || !shelterCells.length) return d
    const c = cellOf(inspect.x, inspect.y, cost.width, cost.height, cost.cellM)
    const r = findRoute(cost, c.i, shelterCells[0], 0, null)
    return { ...d, back: r.reachable ? r.walk_min + ingress : null, backReason: r.reachable ? null : r.reason_text }
  }, [describe, inspect, inspectProbe, cost, shelterCells, ingress])

  const closeNotice = useCallback(() => setNotice(null), [])

  // Presets set the site layers only; crater-wide layers and photo pins keep their own switches.
  const craterIds = new Set((data?.layers ?? []).filter((l) => l.scope).map((l) => l.id))
  const applyPreset = (preset) =>
    setLayerState((s) => {
      const on = presetIds(preset, Object.keys(s))
      return Object.fromEntries(Object.entries(s).map(([id, v]) => [id, craterIds.has(id) ? v : { ...v, on: on.includes(id) }]))
    })
  const isPreset = (preset) => {
    const have = Object.keys(layerState).filter((id) => !craterIds.has(id))
    const on = presetIds(preset, have)
    return have.length > 0 && have.every((id) => !!layerState[id].on === on.includes(id))
  }
  const update = (id, patch) => setLayerState((s) => ({ ...s, [id]: { ...s[id], ...patch } }))

  // A map click (or a click on a pin) while picking.
  const pick = (which, p) => {
    // A point picked on bare ground is named after the mineral there, if CRISM shows one.
    const c = ready ? cellOf(p.x, p.y, cost.width, cost.height, cost.cellM) : null
    const mineral = c ? mineralAt(terrain.mineralImg, terrain.mineralLegend, c.row, c.col, cost.width, cost.height) : null
    const named = p.name ?? (mineral ? `${mineral} area` : null)
    if (which === 'quest') {
      setTrip((m) => ({ ...m, quests: [...m.quests, { x: p.x, y: p.y, name: named ?? `Side quest ${m.quests.length + 1}`, stopMin: params?.stop_min_default ?? 25 }] }))
      return // stay in "add" mode until Done
    }
    if (which === 'landing') {
      if (!landingGrid) return
      // Routing's landing check: safe or marginal stays, anything else moves to the nearest safe cell.
      const chk = landingCheck(landingGrid, p.x, p.y)
      setLandingInfo(chk)
      if (!chk.chosen) return // outside the data: keep picking
      setTrip((m) => ({ ...m, start: { x: chk.chosen.x, y: chk.chosen.y, name: 'Landing' } }))
      if (chk.status === 'moved') setNotice({ title: 'Not a safe place to land', messages: chk.messages, footer: chk.moved_text })
      setPicking(!trip.dest ? 'dest' : null)
      return
    }
    if (which === 'start') {
      // Team outing: any walkable point can be the start. Inside a red zone (lib/escape.js) the route starts
      // with an escape; any other blocked cell is refused with its reason.
      if (!c) return
      const code = cost.mask[c.i]
      if (code && zoneCodes(cost).includes(code)) {
        setStartNote(
          escapeAvailable(cost) && !(cost.escapeTimeRate[c.i] >= 0)
            ? `This start is inside a red zone (${reasonText(cost, code)}). ${reasonText(cost, 'start_too_steep')}, so no route can be planned from here.`
            : escapeAvailable(cost)
            ? `This start is inside a red zone (${reasonText(cost, code)}): the route first walks out of it by the shortest way that still reaches the destination.`
            : `This start is inside a red zone (${reasonText(cost, code)}). Walking out needs an escape rate that routing does not export yet (escape_time_rate), so no route can be planned from here.`,
        )
        setTrip((m) => ({ ...m, start: { x: p.x, y: p.y, name: 'Start' } }))
        setPicking(!trip.dest ? 'dest' : null)
        return
      }
      if (code) {
        const detail = `This point is on a cell the crew may not enter: ${reasonText(cost, code)}. Pick a point nearby that is not blocked.`
        setNotice({ title: 'Not a walkable start', messages: [{ reason: 'start', title: 'Blocked point', detail }] })
        setStartNote(detail)
        return // keep picking
      }
      setStartNote(null)
      setTrip((m) => ({ ...m, start: { x: p.x, y: p.y, name: 'Start' } }))
      setPicking(!trip.dest ? 'dest' : null)
      return
    }
    if (which === 'dest') setTrip((m) => ({ ...m, dest: { x: p.x, y: p.y, name: m.dest?.name || named || 'J0' } }))
    setNotice(null) // the next point is picked: the landing notice has been seen (it stays in the sidebar)
    setPicking(null)
  }
  // Switch mode; each keeps its own trip. My mission asks for a landing first.
  const chooseMode = (m) => {
    setMode(m)
    setTab('route')
    const t = trips[m]
    setPicking(m === 'mission' && (!t.start || !t.dest) ? (t.start ? 'dest' : 'landing') : null)
  }
  // Back to routing's demo route in Team outing.
  const resetOuting = () => {
    setTrips((ts) => ({ ...ts, outing: { ...EMPTY_TRIP, profile: ts.outing.profile } }))
    setDemoOff(false)
    setStartNote(null)
    setPicking(null)
  }
  // Clear route: no route anywhere (map, sidebar, HUD) for the active mode, the demo route included,
  // until the user picks new points. The mode's start, side quests and destination are dropped.
  const clearRoute = () => {
    setTrips((ts) => ({ ...ts, [mode]: { ...EMPTY_TRIP, profile: ts[mode].profile } }))
    if (outing) setDemoOff(true)
    else setLandingInfo(null)
    setStartNote(null)
    setPicking(null)
    setInspect(null)
    setNotice(null)
    setProbe(null)
  }
  const hasRoute = isDemo || !!trip.start || trip.quests.length > 0 || !!trip.dest
  const applyInspected = (which) => {
    if (!inspect) return
    setPicking(null)
    pick(which, inspect)
    setInspect(null)
    setTab('route')
  }
  const copyCoords = async () => {
    if (!inspected?.ll) return
    try {
      await navigator.clipboard.writeText(`${inspected.ll.lat.toFixed(5)}, ${inspected.ll.lon.toFixed(5)}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  const sortQuests = () => {
    if (!ready) return
    const order = bestOrder(cost, trip)
    setTrip((m) => ({ ...m, quests: order.map((k) => m.quests[k]) }))
  }
  const selectStop = (id) => {
    setSelectedStop(id)
    if (id) setTab('route')
  }

  // Sidebar width: drag the edge, use the arrow keys on it, or double-click to reset.
  const dragRef = useRef(null)
  const onDragStart = (e) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = true
    setDragging(true)
  }
  const onDragMove = (e) => {
    if (!dragRef.current) return
    const x = e.clientX
    if (x < SIDEBAR.snapShut) return setSideShut(true)
    setSideShut(false)
    setSideW(Math.round(Math.min(Math.min(SIDEBAR.max, window.innerWidth - 320), Math.max(SIDEBAR.min, x))))
  }
  const onDragEnd = () => {
    dragRef.current = false
    setDragging(false)
  }
  const onDragKey = (e) => {
    const step = e.shiftKey ? 64 : 16
    if (e.key === 'ArrowLeft') setSideW((w) => Math.max(SIDEBAR.min, w - step))
    else if (e.key === 'ArrowRight') setSideW((w) => Math.min(SIDEBAR.max, w + step))
    else if (e.key === 'Enter' || e.key === ' ') setSideShut((s) => !s)
    else return
    e.preventDefault()
  }

  if (error) return <p className="status">Could not load the data: {error}</p>
  if (!data) return <p className="status">Loading…</p>

  const plan = shown.plan
  const names = Object.fromEntries((shown.waypoints?.features ?? []).map((f) => [f.properties.id, f.properties.name]))
  const walkedM = plan ? plan.legs.reduce((s, l) => s + l.distance_m, 0) : 0
  const stopNumber = {}
  stops.forEach((f, k) => (stopNumber[f.properties.id] = k + 1))
  const stop = features.find((f) => f.properties.id === selectedStop)
  const anyFake = data.layers.some((l) => l.source.startsWith('FAKE'))
  const calcNote = craterRoute
    ? `${CRATER_LABEL}, with routing's rules (lib/pathfind.js buildCost); not routing's cost surface`
    : isDemo
    ? "routing's planner (routing/plan_route.py): plan.json as exported, on the same cost surface as data/out/landing"
    : "Calculated in the browser on routing's cost surface (data/out/landing), with the edge rule of routing/docs/DESIGN.md section 15"
  const extras = isDemo ? planExtras(plan) : plan
  const fmtN = (v, f) => (Number.isFinite(v) ? f(v) : '–')
  const profLabel = profInfo?.label
  const shut = sideShut && !visor
  const shelterWord = outing ? 'the start' : 'the landing'
  const notes = data.sources_notes ?? {}
  const mineralLayer = data.layers.find((l) => l.id === 'minerals')

  // Over a limit: the side quest whose removal saves the most time.
  const failing = ok ? plan.checks.filter((c) => !c.ok && c.id !== 'nogo') : []
  const dropHint = failing.length && detours?.length ? detours.map((d, k) => ({ d, k })).filter((x) => x.d).sort((a, b) => b.d.min - a.d.min)[0] : null

  // Every input behind the route numbers, with where it comes from.
  const inputs = params
    ? [
        { id: 'dem', name: 'Heights and slope', value: `HiRISE terrain model on a ${cost?.cellM ?? 5} m grid`, kind: notes['dem.tif'] ? 'real' : 'fake', source: notes['dem.tif'] ?? 'dem.tif, no source given' },
        { id: 'haz', name: 'Hazard classes', value: terrain.hazardInterim ? `From slope: careful over ${params.steep_onset_deg}°, no-go over ${params.slope_max_deg}°` : 'Hazard map from terrain/', kind: 'calc', source: terrain.hazardSource },
        { id: 'speed', name: 'Walking speed', value: `${params.v_flat_kmh} km/h on flat ground, slower on slopes (Tobler's rule)`, kind: 'assumption', source: `Walking model from ${params.from}` },
        { id: 'w', name: 'Mode weights', value: PROFILES.map((p) => `${p.label} w=${params[p.key]}`).join(', '), kind: 'assumption', source: 'Team choice, routing/config.toml [profiles]' },
        { id: 'limits', name: 'Hard limits', value: `Slope ≤ ${params.slope_max_deg}°, ${params.cliff_buffer_m} m from drops, no no-go or no-data cells`, kind: 'assumption', source: 'terrain/thresholds.toml and routing/config.toml' },
        { id: 'time', name: 'Time on site and getting in', value: `${params.stop_min_default} min per stop (unless set), ${params.ingress_min} min into the lander`, kind: 'assumption', source: 'routing/config.toml [timeline]' },
        { id: 'budget', name: 'Time limit', value: `${params.eva_max_min} min minus a ${params.reserve_pct}% reserve = ${Math.round(params.eva_max_min * (1 - params.reserve_pct / 100))} min usable`, kind: 'assumption', source: 'routing/config.toml [timeline]' },
        { id: 'dose', name: 'Radiation', value: `${radModel ? 'radiation.csv' : `${BACKGROUND_USV_H.toFixed(1)} µSv/h`}, limit ${params.radiation_limit_usv} µSv`, kind: 'estimate', source: notes['radiation.csv'] ?? 'Curiosity RAD at Gale crater, 0.64 mSv/day: a stand-in for Jezero' },
        { id: 'min', name: 'Mineral areas', value: 'CRISM summary parameters over a threshold', kind: mineralLayer && !mineralLayer.source.startsWith('FAKE') ? 'real' : 'fake', source: mineralLayer?.source ?? 'No mineral layer' },
        { id: 'geo', name: 'Coordinates', value: `Flat approximation around ${data.site.center_lat}°N, ${data.site.center_lon_east}°E (Mars radius 3,396.19 km)`, kind: 'calc', source: 'web/src/lib/geo.js, good to metres across the site' },
      ]
    : []

  const pointRows = (r) => (
    <>
      {r.pending ? (
        <span className="muted">{crater.status === 'ready' ? 'Reading the crater terrain…' : 'Loading the crater terrain…'}</span>
      ) : r.noData ? (
        <span className="haz h2">No terrain data here: do not enter</span>
      ) : r.inside ? (
        <>
          {r.crater && <span className="res">40 m, rover-scale</span>}
          <span>
            height <b>{Math.round(r.z)} m</b>
          </span>
          <span>
            slope <b>{Number.isFinite(r.slope) ? r.slope.toFixed(1) : '–'}°</b>
          </span>
          <span className={`haz h${r.hazard}`}>{HAZ_WORD[r.hazard]} ground</span>
          {r.ti != null && Number.isFinite(r.ti) && (
            <span>
              thermal inertia <b>{Math.round(r.ti)}</b>
            </span>
          )}
          {r.mineral && <span>{r.mineral}</span>}
          {r.blocked && <span className="haz h2">Blocked: {r.blocked.text}</span>}
          {r.blocked ? null : r.back != null ? (
            <span>
              <b>{Math.round(r.back)} min</b> back to {shelterWord}
            </span>
          ) : r.backPending ? (
            <span className="muted">minutes back: calculating…</span>
          ) : (
            <span className="haz h2">no walking route back{r.backReason ? `: ${r.backReason}` : ''}</span>
          )}
        </>
      ) : (
        <span className="outside">Outside the data: no terrain, no route</span>
      )}
    </>
  )

  return (
    <div
      className={`app${visor ? ' visor' : ''}${view === 'tablet' ? ' tablet' : ''}${shut ? ' shut' : ''}${dragging ? ' dragging' : ''}`}
      style={{ '--sidebar-w': shut ? '0px' : `${sideW}px` }}
    >
      <MissionCard
        data={shown}
        routeLabel={ok ? `${craterRoute ? `${CRATER_LABEL}. ` : ''}${profLabel} route${!isDemo ? `, ${points[0].name} to ${trip.dest?.name || 'destination'}${trip.quests.length ? ` with ${trip.quests.length} side quest${trip.quests.length > 1 ? 's' : ''}` : ''}` : ''}` : null}
      />
      <aside className="sidebar" aria-label="Planning panel" hidden={shut}>
        <div className="side-top">
          <header className="brand">
            <span className="logo" aria-hidden="true" />
            <div>
              <h1>Martian Map</h1>
              <p className="muted">Almost Astral · NASA Space Apps</p>
            </div>
            <button type="button" className="icon-btn" onClick={() => setSideShut(true)} aria-label="Hide the panel" title="Hide the panel">
              <Icon name="left" />
            </button>
          </header>

          <div className="views" role="group" aria-label="View">
            {[
              ['planning', 'Planning'],
              ['hud', 'HUD'],
              ['tablet', 'Tablet'],
            ].map(([id, label]) => (
              <button key={id} className={view === id ? 'active' : ''} aria-pressed={view === id} onClick={() => setView(id)}>
                {label}
              </button>
            ))}
          </div>

          <div className="tabs" role="tablist" aria-label="Panel">
            {TABS.map(([id, label]) => (
              <button key={id} role="tab" id={`tab-${id}`} aria-controls={`panel-${id}`} aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="side-body" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {tab === 'route' && (
            <>
              {stop && (
                <section>
                  {stop ? (
                    <div className="stop-card">
                      <div className="stop-head">
                        <span className="pin">{stopNumber[stop.properties.id]}</span>
                        <strong>{stop.properties.name}</strong>
                        <button onClick={() => setSelectedStop(null)} aria-label="Close stop">
                          <Icon name="close" />
                        </button>
                      </div>
                      <p>{stop.properties.why}</p>
                      <p className="muted">
                        x {stop.geometry.coordinates[0]} m · y {stop.geometry.coordinates[1]} m
                        {data.site.center_lat != null && ` · ${fmtLL(xyToLatLon(...stop.geometry.coordinates, data.site))}`}
                      </p>
                      {!isDemo && stop.properties.kind === 'stop' && (
                        <button type="button" className="ghost-btn" onClick={() => setTrip((m) => ({ ...m, quests: [...m.quests, { x: stop.geometry.coordinates[0], y: stop.geometry.coordinates[1], name: stop.properties.name, stopMin: params?.stop_min_default ?? 25 }] }))}>
                          <Icon name="plus" size={14} /> Add as a side quest
                        </button>
                      )}
                      {stop.properties.photo ? (
                        <figure className="stop-photo">
                          <img src={`./photos/${stop.properties.photo}`} alt={stop.properties.photo_caption ?? stop.properties.name} loading="lazy" />
                          <figcaption>
                            {stop.properties.photo_caption && <span>{stop.properties.photo_caption} </span>}
                            {stop.properties.photo_credit && <span>Credit: {stop.properties.photo_credit}. </span>}
                            {stop.properties.photo_source && (
                              <a href={stop.properties.photo_source} target="_blank" rel="noreferrer">
                                Source
                              </a>
                            )}
                          </figcaption>
                        </figure>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              )}

              <section>
                <h2>Route</h2>
                <div className="presets two" role="group" aria-label="Kind of route">
                  <button className={mode === 'outing' ? 'active' : ''} aria-pressed={mode === 'outing'} onClick={() => chooseMode('outing')}>
                    Team outing
                  </button>
                  <button className={mode === 'mission' ? 'active' : ''} aria-pressed={mode === 'mission'} onClick={() => chooseMode('mission')}>
                    My mission
                  </button>
                </div>

                <div className="route-actions">
                  <button type="button" className="ghost-btn" onClick={clearRoute} disabled={!hasRoute} title="Remove the route from the map, this panel and the HUD">
                    <Icon name="close" size={13} /> Clear route
                  </button>
                  {outing && demoOff && !trip.start && (
                    <button type="button" className="link inline" onClick={resetOuting}>
                      Show routing&apos;s demo route
                    </button>
                  )}
                </div>
                {!hasRoute && <p className="muted">No route. {outing ? 'Pick a start on the map to plan an outing.' : 'Pick a landing site on the map to plan a mission.'}</p>}

                {isDemo && (
                  <p className="muted">
                    Showing routing&apos;s demo route: {data.plan?.start?.name ?? 'the demo start'} to every team stop and back (plan.json, as exported).{' '}
                    {unverified && (
                      <span className="badge" title={unverified}>
                        unverified stops
                      </span>
                    )}{' '}
                    Choose a start to plan your own outing.
                  </p>
                )}
                {outing && trip.start && (
                  <p className="muted">
                    Your own outing, one way.{' '}
                    <button type="button" className="link inline" onClick={resetOuting}>
                      Back to the demo route
                    </button>
                  </p>
                )}
                <RoutePlanner
                  startKind={outing ? 'start' : 'landing'}
                  startNote={outing && startNote ? <p className={`route-check ${rp.inZone && escapeAvailable(cost) && active?.ok ? 'warn' : 'bad'}`}>{startNote}</p> : null}
                  landing={landingInfo}
                  landingReady={!!landingGrid}
                  trip={trip}
                  setTrip={setTrip}
                  picking={picking}
                  setPicking={setPicking}
                  places={places}
                  detours={detours}
                  targets={targets.slice(0, 6)}
                  onBestOrder={sortQuests}
                  defaultStopMin={params?.stop_min_default ?? 25}
                  mineralNote={mineralLayer?.source}
                />
              </section>

              <section>
                <h2>Mode</h2>
                {!ready && <p className="muted">{routeError ? `Route finding needs routing's export in data/out/landing: ${routeError}` : terrain.status === 'missing' ? 'Route finding needs dem.tif, which is missing.' : 'Reading the terrain model and the cost surface…'}</p>}
                {ready && status === 'incomplete' && <p className="muted">{!trip.start ? `Choose ${outing ? 'a start' : 'a landing site'}, then click where you want to go, to see the three routes.` : 'Click where you want to go to see the three routes.'}</p>}
                {craterBusy && <p className="muted routing-busy">Calculating… (route across the crater, 40 m grid)</p>}
                {ready && !allInSite && crater.status === 'error' && <p className="muted">The crater terrain could not be loaded: {crater.error}</p>}
                {ok && craterRoute && (
                  <p className="route-check warn exploratory">
                    <b>{CRATER_LABEL}.</b> Routing&apos;s rules on the CTX DEM at rover scale: it misses boulders and small ledges, and is not one of the planner&apos;s site routes.
                  </p>
                )}
                <ProfileCards results={results} profiles={PROFILES} profile={profile} setProfile={setProfile} usableMin={params?.usable_min} escapeNote={cost?.escape?.note} />
                {active?.ok && active.plan.escape && (
                  <p className="route-check warn">
                    Escape from the red zone: {active.plan.escape.walk_min.toFixed(1)} min, {Math.round(active.plan.escape.distance_m)} m, included in the totals.{' '}
                    {cost?.escape?.note && <span className="escape-note">{cost.escape.note}</span>}
                  </p>
                )}
                {results && !ok && <p className="route-check bad">{unreachableText(active)}</p>}
                {results && ok && active.plan.over_budget && (
                  <p className="route-check warn">
                    Over budget: needs {Math.round(active.plan.needed_min)} min ({active.plan.exact.walk_min.toFixed(1)} walk + {active.plan.totals.stop_min} on site + {active.plan.totals.ingress_min} into the lander), more than the {params.usable_min ?? active.plan.budgets.usable_min} min usable. One way, as routing counts it.
                  </p>
                )}
                {results && ok && (
                  <p className="muted">
                    {profInfo.aim}. <button type="button" className="link inline" onClick={() => setTab('compare')}>Compare the three modes</button>
                  </p>
                )}
              </section>

              {plan && (
                <section>
                  <h2>Plan {ok ? <Tag kind="calc" title={calcNote} /> : plan.fake ? <Tag kind="fake" title="Placeholder plan.json" /> : null}</h2>
                  <div className="plan">
                    <div className="stats">
                      <div>
                        <b>{Math.round(plan.totals.total_min)} min</b>
                        <span>Outing</span>
                      </div>
                      <div>
                        <b>{(walkedM / 1000).toFixed(1)} km</b>
                        <span>Walk</span>
                      </div>
                      <div>
                        <b>{plan.radiation_dose_usv ?? '–'} µSv</b>
                        <span>
                          Dose <Tag kind="estimate" title={notes['radiation.csv'] ?? 'Curiosity RAD at Gale, 0.64 mSv/day'} />
                        </span>
                      </div>
                    </div>
                    {plan.budgets?.eva_max_min && (
                      <div className="budget-wrap">
                        <div className="budget" title={`${Math.round(plan.totals.total_min)} of ${plan.budgets.eva_max_min} min allowed`}>
                          <div className={plan.budgets.usable_min && plan.totals.total_min > plan.budgets.usable_min ? 'over' : ''} style={{ width: `${Math.min(100, (plan.totals.total_min / plan.budgets.eva_max_min) * 100)}%` }} />
                          {plan.budgets.usable_min && <i style={{ left: `${(plan.budgets.usable_min / plan.budgets.eva_max_min) * 100}%` }} />}
                        </div>
                        <small>
                          {Math.round(plan.totals.total_min)} of {plan.budgets.eva_max_min} min allowed <Tag kind="assumption" title="Outing limit and reserve: team choices (routing/config.toml)" />
                        </small>
                      </div>
                    )}
                    {ok && (
                      <>
                        <ul className="checks">
                          {plan.checks.map((c) => (
                            <li key={c.id} className={c.ok ? 'ok' : c.level === 'warn' ? 'warn' : 'bad'}>
                              {c.ok ? '✓' : '!'} {c.message}
                            </li>
                          ))}
                          {!isDemo && <li className="note">One way: the walk ends at {trip.dest?.name || 'the destination'}; no walk back is planned.</li>}
                        </ul>
                        {dropHint && (
                          <p className="route-check warn">
                            Over a limit. Dropping <b>{trip.quests[dropHint.k].name}</b> saves {Math.round(dropHint.d.min)} min.{' '}
                            <button type="button" className="link inline" onClick={() => setTrip((m) => ({ ...m, quests: m.quests.filter((_, j) => j !== dropHint.k) }))}>
                              Drop it
                            </button>
                          </p>
                        )}
                        <div className="safety-grid">
                          <span>Steepest</span>
                          <b>{fmtN(extras.max_slope_deg, (v) => `${v.toFixed(1)}°`)}</b>
                          <span>Climb / descent</span>
                          <b>
                            {fmtN(extras.ascent_m, String)} / {fmtN(extras.descent_m, String)} m
                          </b>
                          <span>On careful ground</span>
                          <b>{fmtN(plan.metres_careful, (v) => `${v} m`)}</b>
                          <span>Furthest from {shelterWord}</span>
                          <b>{furthest ? `${Math.round(furthest.back)} min` : '–'}</b>
                          <span>Walk + on site + into lander</span>
                          <b>
                            {Math.round(plan.totals.walk_min)} + {plan.totals.stop_min} + {plan.totals.ingress_min} min
                          </b>
                        </div>
                      </>
                    )}
                    <ul className="legs">
                      {plan.legs.map((leg, k) => (
                        <li key={`${leg.from}-${leg.to}-${k}`}>
                          <span>
                            {names[leg.from] ?? leg.from} → {names[leg.to] ?? leg.to}
                          </span>
                          <span>
                            {leg.distance_m} m · {Math.round(leg.walk_min)} min{leg.max_slope_deg != null ? ` · max ${leg.max_slope_deg}°` : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <button className="print-btn" onClick={() => window.print()}>
                      Print mission card
                    </button>
                    {isDemo && profile !== 'balanced' && <p className="muted">The legs, checks, timeline and the HUD are routing&apos;s Balanced plan (plan.json); the map and the profile charts show the {profLabel} route file.</p>}
                  </div>
                </section>
              )}

              <RoutePhotos site={data.site} dest={trip.dest} route={ok ? shown.route : null} />

              {plan && ok && (
                <div className="detail">
                  <RouteCharts plan={plan} waypoints={shown.waypoints} route={shown.route} track={track} homeWord={shelterWord} limits={{ yellow: 10, red: params.slope_max_deg }} onProbe={setProbe} hazardNote={terrain.hazardSource} showProfile={false} />
                </div>
              )}
            </>
          )}

          {tab === 'compare' && params && <ModeCompare results={results} profiles={PROFILES} profile={profile} setProfile={setProfile} params={params} inputs={inputs} />}

          {tab === 'layers' && (
            <>
              <section>
                <h2>Layers</h2>
                <div className="presets" role="group" aria-label="Layer presets">
                  {PRESETS.map((p) => (
                    <button key={p.id} className={isPreset(p) ? 'active' : ''} aria-pressed={isPreset(p)} title={p.hint} onClick={() => applyPreset(p)}>
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className="layers">
                  {[...data.layers, ...extraLayers].map((l) => {
                    const on = layerState[l.id]?.on ?? false
                    const fake = l.source.startsWith('FAKE')
                    const open = !!openSource[l.id]
                    return (
                      <div key={l.id} className={`layer${on ? ' on' : ''}`}>
                        <div className="layer-row">
                          <label className="layer-head">
                            <input type="checkbox" className="switch" checked={on} onChange={(e) => update(l.id, { on: e.target.checked })} />
                            <span className="layer-title">
                              {l.title}
                              {fake && <span className="badge">FAKE</span>}
                            </span>
                          </label>
                          <button className="info" onClick={() => setOpenSource((s) => ({ ...s, [l.id]: !s[l.id] }))} aria-expanded={open} aria-label={`Source of ${l.title}`} title="Where this data comes from">
                            i
                          </button>
                        </div>
                        {open && <p className="source">{fake ? l.source.replace(/^FAKE\s*/, 'Fake data ') : l.source}</p>}
                        {on && (
                          <label className="opacity">
                            Opacity
                            <input type="range" min="0" max="1" step="0.05" value={layerState[l.id]?.opacity ?? 1} onChange={(e) => update(l.id, { opacity: Number(e.target.value) })} aria-label={`${l.title} opacity`} />
                          </label>
                        )}
                        {on && l.id === 'minerals' && l.research && <MineralKey shown={mineralsShown} onChange={setMineralsShown} traced={l.research.traced} />}
                      </div>
                    )
                  })}
                </div>
              </section>
              <section>
                <h2>On the map</h2>
                <div className="layers">
                  <label className="layer layer-head">
                    <input type="checkbox" className="switch" checked={gridOn} onChange={(e) => setGridOn(e.target.checked)} />
                    <span className="layer-title">
                      Latitude and longitude grid
                      <small className="sub">Lines follow the zoom level</small>
                    </span>
                  </label>
                  <label className="layer layer-head">
                    <input type="checkbox" className="switch" checked={targetsOn} onChange={(e) => setTargetsOn(e.target.checked)} />
                    <span className="layer-title">
                      Mineral areas for side quests
                      <small className="sub">{allTargets.length} areas from CRISM; the 12 nearest the route show in My mission</small>
                    </span>
                  </label>
                </div>
              </section>
            </>
          )}

          {tab === 'site' && (
            <div className="detail">
              <ConditionsPanel data={data} plan={plan} />
              <WhereIsThis site={data.site} />
              <DataStatus data={data} terrain={terrain} params={params} />
            </div>
          )}
        </div>
      </aside>

      {!visor && (
        <div
          className="resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="Panel width: drag, or use the arrow keys. Enter hides or shows the panel."
          aria-valuenow={shut ? 0 : sideW}
          aria-valuemin={0}
          aria-valuemax={SIDEBAR.max}
          tabIndex={0}
          onPointerDown={onDragStart}
          onPointerMove={onDragMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
          onDoubleClick={() => { setSideShut(false); setSideW(SIDEBAR.start) }}
          onKeyDown={onDragKey}
          title="Drag to resize. Double-click to reset."
        >
          <span />
        </div>
      )}

      <main className={`stage${view === 'hud' ? ' with-hud' : ''}${view === 'hud' && large ? ' large' : ''}${visor ? ' visor' : ''}`}>
        <div className="map-wrap">
          {ok && craterRoute && (
            <p className="exploratory-tag" role="note">
              {CRATER_LABEL}
            </p>
          )}
          <SiteMap
            data={data}
            focusPhoto={focusPhoto}
            extraLayers={extraLayers}
            layerState={layerState}
            route={view === 'hud' ? hudData.route : shown.route}
            altRoutes={view !== 'hud' ? altRoutes : null}
            waypoints={view === 'hud' ? hudData.waypoints : mapWaypoints}
            arrivals={view === 'hud' || !isDemo ? null : arrivals}
            missionPins={view !== 'hud' ? missionPins : null}
            landingPin={view !== 'hud' ? landingPin : null}
            targets={view !== 'hud' && !isDemo && targetsOn ? targets.slice(0, 12) : null}
            picking={view !== 'hud' ? picking : null}
            onPick={pick}
            onInspect={view !== 'hud' ? setInspect : null}
            inspect={view !== 'hud' ? inspect : null}
            gridOn={gridOn}
            onView={(v) => setCentre(v.centre)}
            onHover={setHover}
            probe={probe}
            selectedStop={selectedStop}
            onSelectStop={selectStop}
            astronaut={view === 'hud' ? astronaut : null}
            mineralsShown={layerState.minerals?.on ? mineralsShown : []}
            layoutKey={`${view}-${large}-${visor}`}
            sizeKey={`${shut}-${sideW}`}
          />

          {/* Top-left of the map in every view (Planning, HUD, Tablet, visor): back to the homepage, and the panel when hidden. */}
          <div className="map-actions">
            <a className="map-home" href="#" title="Back to the homepage">
              <Icon name="home" /> Home
            </a>
            {shut && (
              <button type="button" className="panel-open" onClick={() => setSideShut(false)} aria-label="Show the panel">
                <Icon name="panel" /> Panel
              </button>
            )}
          </div>

          <div className="map-chip">
            <strong>{data.site.name}</strong>
            {anyFake && <span className="badge">SOME FAKE DATA</span>}
          </div>

          {picking && view !== 'hud' && (
            <div className="map-hint" role="status">
              {picking === 'landing' ? 'Click the map to choose a landing site' : picking === 'start' ? 'Click the map to choose a start' : picking === 'dest' ? 'Click where you want to go' : 'Click the map, a pin or a mineral area to add side quests'}
              <button type="button" onClick={() => setPicking(null)}>
                {picking === 'quest' ? 'Done' : 'Cancel'}
              </button>
            </div>
          )}

          {notice && view !== 'hud' && <RouteNotice notice={notice} onClose={closeNotice} />}

          {readout && view !== 'hud' && (
            <div className="readout" aria-live="off">
              {pointRows(readout)}
            </div>
          )}

          {view !== 'hud' && (hover || centre) && data.site.center_lat != null && (
            <div className="coords" aria-live="off">
              <span>{hover ? 'Pointer' : 'Map centre'}</span>
              <b>{fmtLL(xyToLatLon((hover ?? centre).x, (hover ?? centre).y, data.site))}</b>
              <small>
                x {Math.round((hover ?? centre).x)} m · y {Math.round((hover ?? centre).y)} m
              </small>
            </div>
          )}

          {inspected && view !== 'hud' && (
            <div className="point-card" role="dialog" aria-label="Point on the map">
              <div className="point-head">
                <Icon name="pin" />
                <b>{inspected.ll ? fmtLL(inspected.ll) : fmtXY(inspected)}</b>
                <button type="button" className="icon-btn" onClick={() => setInspect(null)} aria-label="Close">
                  <Icon name="close" size={14} />
                </button>
              </div>
              <p className="muted">
                x {Math.round(inspected.x)} m · y {Math.round(inspected.y)} m
                {inspected.fromStart && ` · ${Math.round(inspected.fromStart.m)} m ${inspected.fromStart.dir} of ${inspected.fromStart.name} in a straight line`}
              </p>
              <div className="point-facts">{pointRows(inspected)}</div>
              <div className="point-actions">
                <button type="button" onClick={() => applyInspected(outing ? 'start' : 'landing')} disabled={!inspected.inside || (!outing && !landingGrid)}>
                  {outing ? 'Start here' : 'Land here'}
                </button>
                <button type="button" onClick={() => applyInspected('quest')} disabled={!inspected.inside}>
                  <Icon name="plus" size={14} /> Side quest
                </button>
                <button type="button" onClick={() => applyInspected('dest')} disabled={!inspected.inside}>
                  <Icon name="flag" size={14} /> Destination
                </button>
                <button type="button" className="ghost" onClick={copyCoords} disabled={!inspected.ll}>
                  <Icon name="copy" size={14} /> {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          )}

          <div className="map-legend" aria-label="Map key">
            {(layerState.hazard?.on || layerState.hazard_slope?.on) &&
              HAZARD_KEY.map(([colour, label]) => (
                <div key={label}>
                  <i style={{ background: colour }} />
                  {label}
                  {label === 'Fine to walk' && layerState.hazard?.on && data.layers.find((l) => l.id === 'hazard')?.source.startsWith('FAKE') && <span className="badge">FAKE layer</span>}
                  {label === 'Fine to walk' && layerState.hazard_slope?.on && <Tag kind="calc" title={terrain.hazardSource} />}
                </div>
              ))}
            {layerState.minerals?.on &&
              (mineralLayer?.research ? MINERAL_CLASSES.filter((c) => mineralsShown.includes(c.id)).map((c) => ({ label: c.short, color: c.color })) : mineralLayer?.legend ?? []).map((e) => (
                <div key={e.label}>
                  <i style={{ background: e.color }} />
                  {e.label}
                </div>
              ))}
            {layerState.landing_zones?.on &&
              zonesLayer?.legend.map((e) => (
                <div key={`zone-${e.code}`}>
                  <i style={{ background: e.color }} />
                  {e.label}
                  {e.code === 0 && <Tag kind="assumption" title={zonesLayer.source} />}
                </div>
              ))}
            {layerState.thermal?.on && (
              <div className="ramp">
                <span>Thermal inertia</span>
                <i style={{ background: THERMAL_RAMP }} />
                <small>
                  <span>50 loose sand</span>
                  <span>800 rock</span>
                </small>
              </div>
            )}
            {shown.route && (
              <div>
                <i className="line" />
                {view === 'hud' ? (isDemo ? "Routing's Balanced route (plan.json)" : `${profLabel} route`) : `${ok ? profLabel : 'Planned'} route${isDemo ? ' (routing’s file)' : ''}`}
              </div>
            )}
            {active?.ok && active.plan.escape && (
              <div>
                <i className="line escape" />
                Escape from the red zone
              </div>
            )}
            {view !== 'hud' && altRoutes?.length > 0 && (
              <div>
                <i className="line ref" />
                Other modes
              </div>
            )}
            {features.length > 0 && (
              <div>
                <i className="dot" />
                Stop
                {isDemo && view !== 'hud' && (
                  <>
                    <i className="dot m-start" />
                    {data.plan?.start?.name ?? 'Demo start'}
                  </>
                )}
              </div>
            )}
            {!isDemo && view !== 'hud' && (
              <div>
                <i className={`dot ${outing ? 'm-start' : 'landing-safe'}`} />
                {outing ? 'Start' : 'Landing'}
                <i className="dot quest" />
                Side quest
                <i className="dot m-dest" />
                Destination
                {targetsOn && targets.length > 0 && (
                  <>
                    <i className="diamond" />
                    Mineral area
                  </>
                )}
              </div>
            )}
          </div>
        </div>
        {view === 'hud' && (
          <HudView
            key={hudKey}
            data={hudData}
            onPosition={setAstronaut}
            large={large}
            onLarge={setLarge}
            visor={visor}
            onVisor={setVisor}
            profile={track ? { track, limits: { yellow: 10, red: params.slope_max_deg }, hazardNote: terrain.hazardSource, homeWord: shelterWord, onProbe: setProbe } : null}
            emptyText={status === 'failed' ? `No route: ${unreachableText(active)}` : status === 'incomplete' ? `No route yet: choose ${trip.start ? 'a destination' : outing ? 'a start and a destination' : 'a landing site and a destination'}.` : !ready ? 'Reading the terrain and the cost surface…' : null}
          />
        )}
      </main>
    </div>
  )
}

const fmtXY = (p) => `x ${Math.round(p.x)} m, y ${Math.round(p.y)} m`
const fmtLL = (ll) => `${fmtLat(ll.lat)}, ${fmtLon(ll.lon)}`
