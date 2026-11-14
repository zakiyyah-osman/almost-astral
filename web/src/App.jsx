import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import SiteMap from './components/SiteMap.jsx'
import HudView from './hud/HudView.jsx'
import { loadData } from './lib/loadData.js'
import MissionCard from './components/MissionCard.jsx'
import RouteCharts from './components/RouteCharts.jsx'
import ConditionsPanel from './components/ConditionsPanel.jsx'
import WhereIsThis from './components/WhereIsThis.jsx'
import DataStatus from './components/DataStatus.jsx'
import MissionBuilder from './components/MissionBuilder.jsx'
import ModeCompare from './components/ModeCompare.jsx'
import Icon from './components/Icon.jsx'
import Tag from './components/Tag.jsx'
import { buildTimeline, doseTotal, parseTable, radiationModel } from './hud/sim.js'
import { useTerrain, mineralAt } from './lib/useTerrain.js'
import { PROFILES, timeField } from './lib/pathfind.js'
import { planOuting, waypointsFor } from './lib/outing.js'
import { hudPlan } from './lib/hudPlan.js'
import { missionPoints, detourCosts, bestOrder, mineralTargets } from './lib/mission.js'
import { recommendLanding, judgeSpot, LANDING_RULES } from './lib/landing.js'
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
const REASON = {
  start: 'The start is not on walkable ground (or is outside the data).',
  end: 'A point is not on walkable ground (or is outside the data).',
  unreachable: 'No safe way between these points: every path crosses no-go ground.',
}
const BACKGROUND_USV_H = 640 / 24 // routing/config.toml: 0.64 mSv/day (Curiosity RAD at Gale), used only if radiation.csv is missing
const TABS = [
  ['route', 'Route'],
  ['compare', 'Compare'],
  ['layers', 'Layers'],
  ['site', 'Site'],
]
const SIDEBAR = { min: 280, max: 720, start: 360, snapShut: 200 }
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const EMPTY_MISSION = { start: null, quests: [], dest: null, back: true }

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

export default function App() {
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
  const [mode, setMode] = useState('outing') // 'outing': base, every team stop, base. 'mission': start, side quests, destination
  const [profile, setProfile] = useState('balanced')
  const [baseId, setBaseId] = useState('rover') // where the rover parks for a full outing
  const [mission, setMission] = useState(EMPTY_MISSION)
  const [picking, setPicking] = useState(null) // 'start' | 'quest' | 'dest' while waiting for a map click
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
  const visor = visorOn && view === 'hud'

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        const ids = d.layers.map((l) => l.id)
        const start = presetIds(PRESETS[0], ids) // open on the Safety view
        // Crater-wide layers and photo pins start from their own default; the site layers from the Safety preset.
        setLayerState(Object.fromEntries(d.layers.map((l) => [l.id, { on: l.scope ? !!l.default : start.includes(l.id), opacity: l.opacity ?? 1 }])))
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

  const terrain = useTerrain(data)
  const ready = terrain.status === 'ready'
  const cost = terrain.cost
  const params = terrain.params
  const legCache = useMemo(() => new Map(), [cost]) // legs already searched on this terrain

  const features = data?.waypoints?.features ?? []
  const rover = features.find((f) => f.properties.kind === 'rover')
  const stops = features.filter((f) => f.properties.kind === 'stop')
  const asPoint = (f) => ({ id: f.properties.id, name: f.properties.name, kind: f.properties.kind, x: f.geometry.coordinates[0], y: f.geometry.coordinates[1], why: f.properties.why, photo: f.properties.photo, extra: f.properties })

  // Recommended landing spots: flat, clear, short walks to the first and last stop.
  const landing = useMemo(() => {
    if (!ready || !stops.length) return []
    return recommendLanding(cost, [asPoint(stops[0]), asPoint(stops[stops.length - 1])], undefined, stops.map(asPoint)).map((s, k) => ({ ...s, id: `L${k + 1}`, label: `L${k + 1}` }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, cost, data])
  // While the hazard layer is fake, show the interim hazards from the real slope in its place.
  const extraLayers = useMemo(() => (terrain.hazardLayer ? [terrain.hazardLayer] : []), [terrain.hazardLayer])
  useEffect(() => {
    const l = terrain.hazardLayer
    if (!l) return
    setLayerState((st) => (st[l.id] ? st : { ...st, [l.id]: { on: !!st.hazard?.on, opacity: l.opacity }, ...(st.hazard ? { hazard: { ...st.hazard, on: false } } : {}) }))
  }, [terrain.hazardLayer])
  const roverJudge = useMemo(() => (ready && rover ? judgeSpot(cost, ...rover.geometry.coordinates) : null), [ready, cost, rover])

  // Named places for the pickers.
  const places = useMemo(() => {
    const out = []
    if (rover) out.push({ ...asPoint(rover), name: `${rover.properties.name} (team position)` })
    stops.forEach((f, k) => out.push({ ...asPoint(f), name: `${k + 1} · ${f.properties.name}` }))
    landing.forEach((s) => out.push({ id: s.id, name: `${s.label} · recommended landing spot`, kind: 'landing', x: s.x, y: s.y }))
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, landing])

  const radModel = useMemo(() => (radRows?.length ? radiationModel(radRows) : null), [radRows])
  const doseFor = useMemo(() => (min) => (radModel ? doseTotal(radModel, min, null) : (min / 60) * BACKGROUND_USV_H), [radModel])

  // The points of the active route, in walking order.
  const points = useMemo(() => {
    if (mode === 'mission') return params ? missionPoints(mission, params.stop_min_default) : null
    if (!rover) return null
    const base = baseId === 'rover' ? asPoint(rover) : places.find((p) => p.id === baseId)
    if (!base) return null
    const home = { ...base, id: 'rover', kind: 'rover', name: baseId === 'rover' ? rover.properties.name : `Rover at ${base.id}` }
    return [home, ...stops.map(asPoint), home]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, mission, baseId, places, data, params])
  const ingressOn = mode === 'outing' || mission.back
  const planOpts = useMemo(() => ({ ingress: ingressOn, doseFor, cache: legCache }), [ingressOn, doseFor, legCache])

  // Minutes back to shelter from every cell: the start, and the destination too when it has a shelter.
  const back = useMemo(() => {
    if (!ready || !points) return null
    const shelters = [points[0]]
    if (mode === 'mission' && !mission.back) shelters.push(points[points.length - 1])
    const cells = shelters.map((p) => cellOf(p.x, p.y, cost.width, cost.height, cost.cellM)?.i).filter((i) => i != null)
    return cells.length ? timeField(cost, cells) : null
  }, [ready, cost, points, mode, mission.back])
  const ingress = ingressOn ? params?.ingress_min ?? 0 : 0

  // All three modes for the active points, so the crew can compare them.
  const results = useMemo(() => {
    if (!ready || !points) return null
    const out = {}
    for (const p of PROFILES) {
      const r = planOuting(cost, points, params[p.key], params, { ...planOpts, profile: p.id })
      if (r.ok && back) r.furthest = Math.max(...r.track.map((q) => back[q.i]).filter(Number.isFinite)) + ingress
      out[p.id] = r
    }
    return out
  }, [ready, cost, params, points, planOpts, back, ingress])
  const active = results?.[profile]
  const ok = active?.ok
  const profInfo = PROFILES.find((p) => p.id === profile)

  const track = useMemo(() => (ok && back ? active.track.map((p) => ({ ...p, back: back[p.i] + ingress })) : null), [ok, active, back, ingress])
  const furthest = track ? track.reduce((a, b) => (b.back > a.back ? b : a)) : null

  // What each side quest adds, on the active mode.
  const detours = useMemo(() => {
    if (!ready || mode !== 'mission' || !mission.quests.length || !mission.start || !mission.dest) return null
    return detourCosts(cost, mission, params[profInfo.key], params, planOpts)
  }, [ready, cost, params, mode, mission, profInfo, planOpts])

  // Mineral areas from CRISM, and roughly how far each is off the active route (there and back).
  const allTargets = useMemo(() => (ready ? mineralTargets(terrain.mineralImg, terrain.mineralLegend, cost, { minCells: 10 }) : []), [ready, terrain, cost])
  const targets = useMemo(() => {
    if (!allTargets.length) return []
    const cells = ok ? [...new Set(active.track.map((p) => p.i))] : null
    const field = cells?.length ? timeField(cost, cells) : null
    return allTargets
      .map((t) => ({ ...t, detourMin: field && Number.isFinite(field[t.i]) ? 2 * field[t.i] : null }))
      .sort((a, b) => (a.detourMin ?? 1e9) - (b.detourMin ?? 1e9) || b.areaM2 - a.areaM2)
  }, [allTargets, ok, active, cost])

  // What the rest of the app reads: the active route when there is one, else the team's files.
  const activeWaypoints = useMemo(() => (points ? waypointsFor(points) : data?.waypoints), [points, data])
  const shown = ok ? { ...data, plan: active.plan, route: active.route, waypoints: activeWaypoints } : data
  // The HUD walks the same route: the team outing or my mission, on the picked mode. Its slope,
  // height, time back and storm return are worked out from the terrain for this route.
  const hudData = useMemo(
    () => (ok ? { ...data, plan: hudPlan(active.plan, active.track, back, cost, ingress), route: active.route, waypoints: activeWaypoints } : data),
    [ok, data, active, back, cost, ingress, activeWaypoints],
  )
  const hudKey = ok ? `${mode}-${profile}-${active.route.features[0].geometry.coordinates.length}-${active.plan.totals.total_min}` : 'files'
  const arrivals = useMemo(() => {
    if (!ok) return {}
    const tl = buildTimeline(active.plan, activeWaypoints, active.route)
    return Object.fromEntries((tl?.segments ?? []).filter((s) => s.type === 'walk').map((s) => [s.to, s.t1]))
  }, [ok, active, activeWaypoints])

  // Pins on the map: the recommended stops always, and the rover where it parks for this outing.
  const mapWaypoints = useMemo(() => {
    if (!data?.waypoints) return null
    if (mode !== 'outing' || baseId === 'rover' || !points) return data.waypoints
    return { ...data.waypoints, features: data.waypoints.features.map((f) => (f.properties.kind === 'rover' ? { ...f, geometry: { type: 'Point', coordinates: [points[0].x, points[0].y] }, properties: { ...f.properties, name: points[0].name } } : f)) }
  }, [data, mode, baseId, points])

  // The mission's own pins: start, numbered side quests, destination.
  const missionPins = useMemo(() => {
    if (mode !== 'mission') return null
    const t = (id) => (arrivals[id] != null ? ` · T+${Math.floor(arrivals[id] / 60)}:${String(Math.round(arrivals[id] % 60)).padStart(2, '0')}` : '')
    const out = []
    if (mission.start) out.push({ ...mission.start, label: 'S', kind: 'm-start', title: `Start: ${mission.start.name}` })
    mission.quests.forEach((q, k) => out.push({ ...q, label: String(k + 1), kind: 'quest', title: `${q.name}${t(`q${k + 1}`)}` }))
    if (mission.dest) out.push({ ...mission.dest, label: (mission.dest.name || 'J0').slice(0, 2), kind: 'm-dest', title: `${mission.dest.name || 'Destination'}${t('dest')}` })
    return out
  }, [mode, mission, arrivals])

  // Everything known about one point: anywhere on the map, with terrain values where there is data.
  const describe = useCallback(
    (p) => {
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
      if (!c) return out
      return {
        ...out,
        inside: true,
        z: cost.dem[c.i],
        slope: cost.slope[c.i],
        hazard: cost.hazard[c.i],
        ti: terrain.ti ? terrain.ti.data[c.i] : null,
        mineral: mineralAt(terrain.mineralImg, terrain.mineralLegend, c.row, c.col, cost.width, cost.height),
        back: back && Number.isFinite(back[c.i]) ? back[c.i] + ingress : null,
      }
    },
    [data, ready, cost, terrain, back, ingress, points],
  )
  const readout = useMemo(() => describe(hover), [describe, hover])
  const inspected = useMemo(() => describe(inspect), [describe, inspect])

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
      setMission((m) => ({ ...m, quests: [...m.quests, { x: p.x, y: p.y, name: named ?? `Side quest ${m.quests.length + 1}`, stopMin: params?.stop_min_default ?? 25 }] }))
      return // stay in "add" mode until Done
    }
    if (which === 'start') setMission((m) => ({ ...m, start: { x: p.x, y: p.y, name: named ?? 'Point S' } }))
    if (which === 'dest') setMission((m) => ({ ...m, dest: { x: p.x, y: p.y, name: m.dest?.name || named || 'J0' } }))
    setPicking(which === 'start' && !mission.dest ? 'dest' : null)
  }
  const startMission = () => {
    setMode('mission')
    setTab('route')
    setMission((m) => (m.start ? m : { ...m, start: rover ? { x: rover.geometry.coordinates[0], y: rover.geometry.coordinates[1], name: rover.properties.name } : null }))
    if (!mission.dest) setPicking(rover || mission.start ? 'dest' : 'start')
  }
  const applyInspected = (which) => {
    if (!inspect) return
    if (mode !== 'mission') {
      setMode('mission')
      if (which !== 'start' && !mission.start && rover) setMission((m) => ({ ...m, start: { x: rover.geometry.coordinates[0], y: rover.geometry.coordinates[1], name: rover.properties.name } }))
    }
    pick(which, inspect)
    setPicking(null)
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
    const order = bestOrder(cost, mission)
    setMission((m) => ({ ...m, quests: order.map((k) => m.quests[k]) }))
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
  const landSel = landing.find((s) => s.id === selectedStop)
  const anyFake = data.layers.some((l) => l.source.startsWith('FAKE'))
  const calcNote = `Calculated on the HiRISE terrain model with the walking model from ${params?.from ?? 'routing/config.toml'}`
  const profLabel = profInfo?.label
  const shut = sideShut && !visor
  const shelterWord = mode === 'outing' ? 'the rover' : mission.back ? 'the start' : 'shelter'
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
        { id: 'time', name: 'Time on site and getting in', value: `${params.stop_min_default} min per stop (unless set), ${params.ingress_min} min into the rover`, kind: 'assumption', source: 'routing/config.toml [timeline]' },
        { id: 'budget', name: 'Time limit', value: `${params.eva_max_min} min minus a ${params.reserve_pct}% reserve = ${Math.round(params.eva_max_min * (1 - params.reserve_pct / 100))} min usable`, kind: 'assumption', source: 'routing/config.toml [timeline]' },
        { id: 'dose', name: 'Radiation', value: `${radModel ? 'radiation.csv' : `${BACKGROUND_USV_H.toFixed(1)} µSv/h`}, limit ${params.radiation_limit_usv} µSv`, kind: 'estimate', source: notes['radiation.csv'] ?? 'Curiosity RAD at Gale crater, 0.64 mSv/day: a stand-in for Jezero' },
        { id: 'min', name: 'Mineral areas', value: 'CRISM summary parameters over a threshold', kind: mineralLayer && !mineralLayer.source.startsWith('FAKE') ? 'real' : 'fake', source: mineralLayer?.source ?? 'No mineral layer' },
        { id: 'geo', name: 'Coordinates', value: `Flat approximation around ${data.site.center_lat}°N, ${data.site.center_lon_east}°E (Mars radius 3,396.19 km)`, kind: 'calc', source: 'web/src/lib/geo.js, good to metres across the site' },
      ]
    : []

  const pointRows = (r) => (
    <>
      {r.inside ? (
        <>
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
          {r.back != null ? (
            <span>
              <b>{Math.round(r.back)} min</b> back to {shelterWord}
            </span>
          ) : (
            <span className="haz h2">no safe way back</span>
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
        routeLabel={ok ? `${profLabel} route${mode === 'mission' ? `, ${points[0].name} to ${mission.dest?.name || 'destination'}${mission.quests.length ? ` with ${mission.quests.length} side quest${mission.quests.length > 1 ? 's' : ''}` : ''}` : ''}` : null}
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
              {(stop || landSel) && (
                <section>
                  {stop ? (
                    <div className="stop-card">
                      <div className="stop-head">
                        <span className={`pin${stop.properties.kind === 'rover' ? ' rover' : ''}`}>{stop.properties.kind === 'rover' ? 'R' : stopNumber[stop.properties.id]}</span>
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
                      {mode === 'mission' && stop.properties.kind === 'stop' && (
                        <button type="button" className="ghost-btn" onClick={() => setMission((m) => ({ ...m, quests: [...m.quests, { x: stop.geometry.coordinates[0], y: stop.geometry.coordinates[1], name: stop.properties.name, stopMin: params?.stop_min_default ?? 25 }] }))}>
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
                  ) : (
                    <div className="stop-card">
                      <div className="stop-head">
                        <span className="pin landing">{landSel.label}</span>
                        <strong>Recommended landing spot</strong>
                        <button onClick={() => setSelectedStop(null)} aria-label="Close">
                          <Icon name="close" />
                        </button>
                      </div>
                      <p>
                        Flat, clear ground (average slope {landSel.meanSlope.toFixed(1)}° within {LANDING_RULES.radiusM} m). {Math.round(landSel.walkFirstMin)} min walk to stop 1 and{' '}
                        {Math.round(landSel.walkLastMin)} min back from stop {stops.length}.
                      </p>
                      <p className="muted">{data.site.center_lat != null && fmtLL(xyToLatLon(landSel.x, landSel.y, data.site))}</p>
                    </div>
                  )}
                </section>
              )}

              <section>
                <h2>Route</h2>
                <div className="presets two" role="group" aria-label="Kind of route">
                  <button className={mode === 'outing' ? 'active' : ''} aria-pressed={mode === 'outing'} onClick={() => { setMode('outing'); setPicking(null) }}>
                    Team outing
                  </button>
                  <button className={mode === 'mission' ? 'active' : ''} aria-pressed={mode === 'mission'} onClick={startMission}>
                    My mission
                  </button>
                </div>

                {mode === 'outing' ? (
                  <label className="field">
                    Start and finish at
                    <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
                      <option value="rover">Rover, team position</option>
                      {landing.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}, recommended landing spot
                        </option>
                      ))}
                    </select>
                    <small className="muted">Then every team stop in order, and back.</small>
                  </label>
                ) : (
                  <MissionBuilder
                    mission={mission}
                    setMission={setMission}
                    picking={picking}
                    setPicking={setPicking}
                    places={places}
                    detours={detours}
                    targets={targets.slice(0, 6)}
                    onBestOrder={sortQuests}
                    defaultStopMin={params?.stop_min_default ?? 25}
                    mineralNote={mineralLayer?.source}
                  />
                )}
              </section>

              <section>
                <h2>Mode</h2>
                {!ready && <p className="muted">{terrain.status === 'loading' ? 'Reading the terrain model…' : 'Route finding needs dem.tif, which is missing.'}</p>}
                {ready && !points && <p className="muted">Set a start and a destination to see the three routes.</p>}
                {results && (
                  <div className="profiles" role="group" aria-label="Route mode">
                    {PROFILES.map((p) => {
                      const r = results[p.id]
                      const bad = r.ok && r.plan.checks.some((c) => !c.ok)
                      return (
                        <button key={p.id} className={`${profile === p.id ? 'active' : ''}${bad ? ' over' : ''}`} aria-pressed={profile === p.id} onClick={() => setProfile(p.id)} disabled={!r.ok}>
                          <b>{p.label}</b>
                          {r.ok ? (
                            <>
                              <span>{(r.plan.legs.reduce((s, l) => s + l.distance_m, 0) / 1000).toFixed(2)} km</span>
                              <span>{Math.round(r.plan.totals.total_min)} min total</span>
                              <span>{r.plan.risk_min.toFixed(1)} min risky</span>
                              {bad && <em>over a limit</em>}
                            </>
                          ) : (
                            <span>no route</span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                )}
                {results && !ok && <p className="route-check bad">{REASON[active?.reason] ?? 'No route.'}</p>}
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
                            <li key={c.id} className={c.ok ? 'ok' : 'bad'}>
                              {c.ok ? '✓' : '!'} {c.message}
                            </li>
                          ))}
                          {mode === 'mission' && !mission.back && <li className="note">Ends at {mission.dest?.name || 'the destination'}: it must have a shelter.</li>}
                        </ul>
                        {dropHint && (
                          <p className="route-check warn">
                            Over a limit. Dropping <b>{mission.quests[dropHint.k].name}</b> saves {Math.round(dropHint.d.min)} min.{' '}
                            <button type="button" className="link inline" onClick={() => setMission((m) => ({ ...m, quests: m.quests.filter((_, j) => j !== dropHint.k) }))}>
                              Drop it
                            </button>
                          </p>
                        )}
                        <div className="safety-grid">
                          <span>Steepest</span>
                          <b>{plan.max_slope_deg.toFixed(1)}°</b>
                          <span>Climb / descent</span>
                          <b>
                            {plan.ascent_m} / {plan.descent_m} m
                          </b>
                          <span>On careful ground</span>
                          <b>{plan.metres_careful} m</b>
                          <span>Furthest from {shelterWord}</span>
                          <b>{furthest ? `${Math.round(furthest.back)} min` : '–'}</b>
                          <span>Walk + on site + into rover</span>
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
                    {view === 'hud' && ok && <p className="muted">The HUD simulation follows the team planner&apos;s route (route.geojson), not the route picked here.</p>}
                  </div>
                </section>
              )}

              {plan && ok && (
                <div className="detail">
                  <RouteCharts plan={plan} waypoints={shown.waypoints} route={shown.route} track={track} limits={{ yellow: 10, red: params.slope_max_deg }} onProbe={setProbe} hazardNote={terrain.hazardSource} />
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
              {ready && (
                <section>
                  <h2>
                    Landing spots{' '}
                    <Tag
                      kind="calc"
                      title={`Flat pad: average slope at most ${LANDING_RULES.maxMeanSlopeDeg}° and no cell over ${LANDING_RULES.maxSlopeDeg}° within ${LANDING_RULES.radiusM} m, nothing blocked. Criterion follows the human-landing rule of slopes under about 5° (Golombek et al., LPSC 2021). Ranked by walking time to the first stop and back from the last.`}
                    />
                  </h2>
                  {landing.length ? (
                    <ul className="landing-list">
                      {landing.map((s) => (
                        <li key={s.id} className={baseId === s.id && mode === 'outing' ? 'on' : ''}>
                          <span className="pin landing">{s.label}</span>
                          <span>
                            avg slope {s.meanSlope.toFixed(1)}° · {Math.round(s.walkFirstMin)} min to stop 1, {Math.round(s.walkLastMin)} min back from stop {stops.length}
                          </span>
                          <button onClick={() => { setMode('outing'); setBaseId(s.id); setTab('route') }}>Use</button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">No pad in the site is flat and clear enough.</p>
                  )}
                  {roverJudge && (
                    <p className={`route-check ${roverJudge.ok ? 'ok' : 'warn'}`}>
                      Team rover position: slope {roverJudge.slopeHere.toFixed(1)}° there, {Number.isFinite(roverJudge.meanSlope) ? `average ${roverJudge.meanSlope.toFixed(1)}° around it` : 'too near the edge to judge'}.{' '}
                      {roverJudge.ok ? 'It meets the landing rules.' : 'It does not meet the landing rules: consider a recommended spot.'}
                    </p>
                  )}
                </section>
              )}
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
          <SiteMap
            data={data}
            extraLayers={extraLayers}
            layerState={layerState}
            route={view === 'hud' ? hudData.route : shown.route}
            refRoute={view !== 'hud' && ok && mode === 'outing' ? data.route : null}
            waypoints={view === 'hud' ? hudData.waypoints : mapWaypoints}
            arrivals={view === 'hud' || mode !== 'outing' ? null : arrivals}
            landing={view === 'hud' ? [] : landing.map((s) => ({ ...s, title: `${s.label}: recommended landing spot` }))}
            missionPins={view !== 'hud' ? missionPins : null}
            targets={view !== 'hud' && mode === 'mission' && targetsOn ? targets.slice(0, 12) : null}
            picking={view !== 'hud' && mode === 'mission' ? picking : null}
            onPick={pick}
            onInspect={view !== 'hud' ? setInspect : null}
            inspect={view !== 'hud' ? inspect : null}
            gridOn={gridOn}
            onView={(v) => setCentre(v.centre)}
            onHover={setHover}
            probe={view === 'hud' ? null : probe}
            selectedStop={selectedStop}
            onSelectStop={selectStop}
            astronaut={view === 'hud' ? astronaut : null}
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
              {picking === 'start' ? 'Click the map or a pin to set the start' : picking === 'dest' ? 'Click the map or a pin to set the destination' : 'Click the map, a pin or a mineral area to add side quests'}
              <button type="button" onClick={() => setPicking(null)}>
                {picking === 'quest' ? 'Done' : 'Cancel'}
              </button>
            </div>
          )}

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
                <button type="button" onClick={() => applyInspected('start')} disabled={!inspected.inside}>
                  Start here
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
              (mineralLayer?.legend ?? []).map((e) => (
                <div key={e.label}>
                  <i style={{ background: e.color }} />
                  {e.label}
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
                {view === 'hud' ? 'Team planned route' : `${ok ? profLabel : 'Planned'} route`}
              </div>
            )}
            {view !== 'hud' && ok && mode === 'outing' && data.route && (
              <div>
                <i className="line ref" />
                Team planner route
              </div>
            )}
            {features.length > 0 && (
              <div>
                <i className="dot" />
                Stop
                <i className="dot rover" />
                Rover
                {landing.length > 0 && view !== 'hud' && (
                  <>
                    <i className="dot landing" />
                    Landing
                  </>
                )}
              </div>
            )}
            {mode === 'mission' && view !== 'hud' && (
              <div>
                <i className="dot m-start" />
                Start
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
        {view === 'hud' && <HudView key={hudKey} data={hudData} onPosition={setAstronaut} large={large} onLarge={setLarge} visor={visor} onVisor={setVisor} />}
      </main>
    </div>
  )
}

const fmtXY = (p) => `x ${Math.round(p.x)} m, y ${Math.round(p.y)} m`
const fmtLL = (ll) => `${fmtLat(ll.lat)}, ${fmtLon(ll.lon)}`
