import { useEffect, useMemo, useState } from 'react'
import SiteMap from './components/SiteMap.jsx'
import HudView from './hud/HudView.jsx'
import { loadData } from './lib/loadData.js'
import MissionCard from './components/MissionCard.jsx'
import RouteCharts from './components/RouteCharts.jsx'
import ConditionsPanel from './components/ConditionsPanel.jsx'
import WhereIsThis from './components/WhereIsThis.jsx'
import DataStatus from './components/DataStatus.jsx'
import Tag from './components/Tag.jsx'
import { buildTimeline, doseTotal, parseTable, radiationModel } from './hud/sim.js'
import { useTerrain, mineralAt } from './lib/useTerrain.js'
import { PROFILES, timeField } from './lib/pathfind.js'
import { planOuting, waypointsFor } from './lib/outing.js'
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
const REASON = { start: 'The start is not on walkable ground.', end: 'The end is not on walkable ground.', unreachable: 'No safe way between these points: every path crosses no-go ground.' }
const BACKGROUND_USV_H = 640 / 24 // routing/config.toml: 0.64 mSv/day (Curiosity RAD at Gale), used only if radiation.csv is missing

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [layerState, setLayerState] = useState({})
  const [view, setView] = useState('planning')
  const [selectedStop, setSelectedStop] = useState(null)
  const [astronaut, setAstronaut] = useState(null) // set by the HUD while it simulates
  const [large, setLarge] = useState(false) // big text for a projector
  const [visorOn, setVisor] = useState(false) // full-screen visor view
  const [openSource, setOpenSource] = useState({}) // layers whose source line is expanded
  const [mode, setMode] = useState('outing') // 'outing': base, every stop, base. 'custom': point A to point B
  const [profile, setProfile] = useState('balanced')
  const [baseId, setBaseId] = useState('rover') // where the rover parks for a full outing
  const [ends, setEnds] = useState({}) // custom route: { start: {x, y, name}, end: {x, y, name} }
  const [picking, setPicking] = useState(null) // 'start' | 'end' while waiting for a map click
  const [hover, setHover] = useState(null)
  const [probe, setProbe] = useState(null)
  const [radRows, setRadRows] = useState(null)
  const visor = visorOn && view === 'hud'

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        const ids = d.layers.map((l) => l.id)
        const start = presetIds(PRESETS[0], ids) // open on the Safety view
        // Crater-wide layers start from their own default; the site layers from the Safety preset.
        setLayerState(Object.fromEntries(d.layers.map((l) => [l.id, { on: l.scope === 'crater' ? !!l.default : start.includes(l.id), opacity: l.opacity ?? 1 }])))
        if (d.tables?.radiation) {
          fetch(`./${d.tables.radiation}`)
            .then((r) => (r.ok ? r.text() : ''))
            .then((t) => setRadRows(parseTable(t)))
            .catch(() => setRadRows([]))
        }
      })
      .catch((e) => setError(e.message))
  }, [])

  const terrain = useTerrain(data)
  const ready = terrain.status === 'ready'
  const cost = terrain.cost
  const params = terrain.params

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
    if (mode === 'custom') {
      if (!ends.start || !ends.end) return null
      return [
        { id: 'start', kind: 'rover', name: ends.start.name ?? 'Point A', x: ends.start.x, y: ends.start.y },
        { id: 'end', kind: 'point', name: ends.end.name ?? 'Point B', x: ends.end.x, y: ends.end.y },
      ]
    }
    if (!rover) return null
    const base = baseId === 'rover' ? asPoint(rover) : places.find((p) => p.id === baseId)
    if (!base) return null
    const home = { ...base, id: 'rover', kind: 'rover', name: baseId === 'rover' ? rover.properties.name : `Rover at ${base.id}` }
    return [home, ...stops.map(asPoint), home]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, ends, baseId, places, data])

  // All three profiles for the active points, so the crew can compare them.
  const results = useMemo(() => {
    if (!ready || !points) return null
    const out = {}
    for (const p of PROFILES) out[p.id] = planOuting(cost, points, params[p.key], params, { ingress: mode === 'outing', doseFor, profile: p.id })
    return out
  }, [ready, cost, params, points, mode, doseFor])
  const active = results?.[profile]
  const ok = active?.ok

  // Minutes back to the start of the route from every point (ingress added for a full outing).
  const back = useMemo(() => {
    if (!ready || !points) return null
    const c = cellOf(points[0].x, points[0].y, cost.width, cost.height, cost.cellM)
    return c ? timeField(cost, c.i) : null
  }, [ready, cost, points])
  const ingress = mode === 'outing' ? params?.ingress_min ?? 0 : 0
  const track = useMemo(() => (ok && back ? active.track.map((p) => ({ ...p, back: back[p.i] + ingress })) : null), [ok, active, back, ingress])
  const furthest = track ? track.reduce((a, b) => (b.back > a.back ? b : a)) : null

  // What the rest of the app reads: the active route when there is one, else the team's files.
  const activeWaypoints = useMemo(() => (points ? waypointsFor(points) : data?.waypoints), [points, data])
  const shown = ok ? { ...data, plan: active.plan, route: active.route, waypoints: activeWaypoints } : data
  const arrivals = useMemo(() => {
    if (!ok || mode !== 'outing') return {}
    const tl = buildTimeline(active.plan, activeWaypoints, active.route)
    return Object.fromEntries((tl?.segments ?? []).filter((s) => s.type === 'walk').map((s) => [s.to, s.t1]))
  }, [ok, active, activeWaypoints, mode])

  // Pins on the map: the recommended stops always, and the rover where it parks for this outing.
  const mapWaypoints = useMemo(() => {
    if (!data?.waypoints) return null
    if (mode !== 'outing' || baseId === 'rover' || !points) return data.waypoints
    return { ...data.waypoints, features: data.waypoints.features.map((f) => (f.properties.kind === 'rover' ? { ...f, geometry: { type: 'Point', coordinates: [points[0].x, points[0].y] }, properties: { ...f.properties, name: points[0].name } } : f)) }
  }, [data, mode, baseId, points])

  // What is under the pointer.
  const readout = useMemo(() => {
    if (!ready || !hover) return null
    const c = cellOf(hover.x, hover.y, cost.width, cost.height, cost.cellM)
    if (!c) return null
    const ll = data.site.center_lat != null ? xyToLatLon(hover.x, hover.y, data.site) : null
    return {
      x: hover.x,
      y: hover.y,
      ll,
      z: cost.dem[c.i],
      slope: cost.slope[c.i],
      hazard: cost.hazard[c.i],
      ti: terrain.ti ? terrain.ti.data[c.i] : null,
      mineral: mineralAt(terrain.mineralImg, terrain.mineralLegend, c.row, c.col, cost.width, cost.height),
      back: back && Number.isFinite(back[c.i]) ? back[c.i] + ingress : null,
    }
  }, [ready, hover, cost, terrain, back, ingress, data])

  // Presets set the site layers only; crater-wide layers keep their own switches.
  const craterIds = new Set((data?.layers ?? []).filter((l) => l.scope === 'crater').map((l) => l.id))
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
  const pick = (which, p) => {
    setEnds((e) => ({ ...e, [which]: { x: p.x, y: p.y, name: which === 'start' ? 'Point A' : 'Point B' } }))
    setPicking(which === 'start' && !ends.end ? 'end' : null)
  }
  const setEndFromPlace = (which, id) => {
    const p = places.find((q) => q.id === id)
    if (p) setEnds((e) => ({ ...e, [which]: { x: p.x, y: p.y, name: p.name } }))
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
  const profLabel = PROFILES.find((p) => p.id === profile)?.label

  return (
    <div className={`app${visor ? ' visor' : ''}${view === 'tablet' ? ' tablet' : ''}`}>
      <MissionCard data={shown} routeLabel={ok ? `${profLabel} route${mode === 'custom' ? `, ${points[0].name} to ${points[1].name}` : ''}` : null} />
      <aside className="sidebar">
        <header className="brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <h1>Martian Map</h1>
            <p className="muted">Almost Astral · NASA Space Apps</p>
          </div>
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

        <section>
          <h2>Route</h2>
          <div className="presets two" role="group" aria-label="Kind of route">
            <button className={mode === 'outing' ? 'active' : ''} aria-pressed={mode === 'outing'} onClick={() => { setMode('outing'); setPicking(null) }}>
              Full outing
            </button>
            <button className={mode === 'custom' ? 'active' : ''} aria-pressed={mode === 'custom'} onClick={() => { setMode('custom'); if (!ends.start) setPicking('start') }}>
              Point to point
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
              <small className="muted">Then every recommended stop in order, and back.</small>
            </label>
          ) : (
            <div className="ends">
              {[
                ['start', 'A', 'Start'],
                ['end', 'B', 'End'],
              ].map(([which, letter, word]) => (
                <div key={which} className="end-row">
                  <span className={`pin end-${which}`}>{letter}</span>
                  <select value="" onChange={(e) => setEndFromPlace(which, e.target.value)} aria-label={`${word} from a list`}>
                    <option value="">{ends[which] ? (ends[which].name.startsWith('Point') ? `${fmtXY(ends[which])}` : ends[which].name) : `${word}: pick a place…`}</option>
                    {places.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <button className={picking === which ? 'active' : ''} onClick={() => setPicking(picking === which ? null : which)}>
                    {picking === which ? 'Click the map…' : 'On map'}
                  </button>
                </div>
              ))}
              <button className="link" onClick={() => setEnds((e) => ({ start: e.end, end: e.start }))} disabled={!ends.start || !ends.end}>
                Swap A and B
              </button>
            </div>
          )}

          {!ready && <p className="muted">{terrain.status === 'loading' ? 'Reading the terrain model…' : 'Route finding needs dem.tif, which is missing.'}</p>}
          {results && (
            <div className="profiles" role="group" aria-label="Route profile">
              {PROFILES.map((p) => {
                const r = results[p.id]
                return (
                  <button key={p.id} className={profile === p.id ? 'active' : ''} aria-pressed={profile === p.id} onClick={() => setProfile(p.id)} disabled={!r.ok}>
                    <b>{p.label}</b>
                    {r.ok ? (
                      <>
                        <span>{(r.plan.legs.reduce((s, l) => s + l.distance_m, 0) / 1000).toFixed(2)} km</span>
                        <span>{Math.round(r.plan.totals.walk_min)} min walk</span>
                        <span>{r.plan.risk_min.toFixed(1)} min risky</span>
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
          {ready && (
            <p className="muted">
              Never enters ground over {params.slope_max_deg}°. Risky minutes are time on careful ground (10–{params.slope_max_deg}°) or within {params.near_red_radius_m} m of no-go
              ground. Hazards: <Tag kind="calc" title={terrain.hazardSource} /> {terrain.hazardInterim && 'from the real slope until the hazard layer is real.'}
            </p>
          )}
        </section>

        {plan && (
          <section>
            <h2>
              Plan {ok ? <Tag kind="calc" title={calcNote} /> : plan.fake ? <Tag kind="fake" title="Placeholder plan.json" /> : null}
            </h2>
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
                    Dose <Tag kind="estimate" title={data.sources_notes?.['radiation.csv'] ?? 'Curiosity RAD at Gale, 0.64 mSv/day'} />
                  </span>
                </div>
              </div>
              {plan.budgets?.eva_max_min && (
                <div className="budget-wrap">
                  <div className="budget" title={`${Math.round(plan.totals.total_min)} of ${plan.budgets.eva_max_min} min allowed`}>
                    <div style={{ width: `${Math.min(100, (plan.totals.total_min / plan.budgets.eva_max_min) * 100)}%` }} />
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
                  </ul>
                  <div className="safety-grid">
                    <span>Steepest</span>
                    <b>{plan.max_slope_deg.toFixed(1)}°</b>
                    <span>Climb / descent</span>
                    <b>
                      {plan.ascent_m} / {plan.descent_m} m
                    </b>
                    <span>On careful ground</span>
                    <b>{plan.metres_careful} m</b>
                    <span>Furthest from {mode === 'outing' ? 'the rover' : 'A'}</span>
                    <b>{furthest ? `${Math.round(furthest.back)} min` : '–'}</b>
                    {mode === 'outing' && (
                      <>
                        <span>Walk, stops, into rover</span>
                        <b>
                          {Math.round(plan.totals.walk_min)} + {plan.totals.stop_min} + {plan.totals.ingress_min} min
                        </b>
                      </>
                    )}
                  </div>
                </>
              )}
              <button className="print-btn" onClick={() => window.print()}>
                Print mission card
              </button>
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
              {view === 'hud' && ok && (
                <p className="muted">The HUD simulation follows the team planner&apos;s route (route.geojson), not the route picked here.</p>
              )}
            </div>
          </section>
        )}

        {ready && (
          <section>
            <h2>
              Landing spots <Tag kind="calc" title={`Flat pad: average slope at most ${LANDING_RULES.maxMeanSlopeDeg}° and no cell over ${LANDING_RULES.maxSlopeDeg}° within ${LANDING_RULES.radiusM} m, nothing blocked. Criterion follows the human-landing rule of slopes under about 5° (Golombek et al., LPSC 2021). Ranked by walking time to the first stop and back from the last.`} />
            </h2>
            {landing.length ? (
              <ul className="landing-list">
                {landing.map((s) => (
                  <li key={s.id} className={baseId === s.id && mode === 'outing' ? 'on' : ''}>
                    <span className="pin landing">{s.label}</span>
                    <span>
                      avg slope {s.meanSlope.toFixed(1)}° · {Math.round(s.walkFirstMin)} min to stop 1, {Math.round(s.walkLastMin)} min back from stop {stops.length}
                    </span>
                    <button onClick={() => { setMode('outing'); setBaseId(s.id) }}>Use</button>
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

        {features.length > 0 && (
          <section>
            <h2>Stop</h2>
            {stop ? (
              <div className="stop-card">
                <div className="stop-head">
                  <span className={`pin${stop.properties.kind === 'rover' ? ' rover' : ''}`}>{stop.properties.kind === 'rover' ? 'R' : stopNumber[stop.properties.id]}</span>
                  <strong>{stop.properties.name}</strong>
                  <button onClick={() => setSelectedStop(null)} aria-label="Close stop">
                    ×
                  </button>
                </div>
                <p>{stop.properties.why}</p>
                <p className="muted">
                  x {stop.geometry.coordinates[0]} m · y {stop.geometry.coordinates[1]} m
                  {data.site.center_lat != null && ` · ${fmtLL(xyToLatLon(...stop.geometry.coordinates, data.site))}`}
                </p>
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
            ) : landSel ? (
              <div className="stop-card">
                <div className="stop-head">
                  <span className="pin landing">{landSel.label}</span>
                  <strong>Recommended landing spot</strong>
                  <button onClick={() => setSelectedStop(null)} aria-label="Close">
                    ×
                  </button>
                </div>
                <p>
                  Flat, clear ground (average slope {landSel.meanSlope.toFixed(1)}° within {LANDING_RULES.radiusM} m). {Math.round(landSel.walkFirstMin)} min walk to stop 1 and{' '}
                  {Math.round(landSel.walkLastMin)} min back from stop {stops.length}.
                </p>
                <p className="muted">{data.site.center_lat != null && fmtLL(xyToLatLon(landSel.x, landSel.y, data.site))}</p>
              </div>
            ) : (
              <p className="muted">Click a numbered stop or a landing spot (L) on the map to see what is there.</p>
            )}
          </section>
        )}

        <div className="detail">
          {plan && ok && <RouteCharts plan={plan} waypoints={shown.waypoints} route={shown.route} track={track} limits={{ yellow: 10, red: params.slope_max_deg }} onProbe={setProbe} hazardNote={terrain.hazardSource} />}
          <ConditionsPanel data={data} plan={plan} />
          <WhereIsThis site={data.site} />
          <DataStatus data={data} terrain={terrain} params={params} />
        </div>

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
      </aside>

      <main className={`stage${view === 'hud' ? ' with-hud' : ''}${view === 'hud' && large ? ' large' : ''}${visor ? ' visor' : ''}`}>
        <div className="map-wrap">
          <SiteMap
            data={data}
            extraLayers={extraLayers}
            layerState={layerState}
            route={view === 'hud' ? data.route : shown.route}
            refRoute={view !== 'hud' && ok ? data.route : null}
            waypoints={view === 'hud' ? data.waypoints : mapWaypoints}
            arrivals={view === 'hud' ? null : arrivals}
            landing={view === 'hud' ? [] : landing.map((s) => ({ ...s, title: `${s.label}: recommended landing spot` }))}
            ends={view !== 'hud' && mode === 'custom' ? ends : null}
            picking={view !== 'hud' && mode === 'custom' ? picking : null}
            onPick={pick}
            onHover={setHover}
            probe={view === 'hud' ? null : probe}
            selectedStop={selectedStop}
            onSelectStop={setSelectedStop}
            astronaut={view === 'hud' ? astronaut : null}
            layoutKey={`${view}-${large}-${visor}`}
          />

          <div className="map-chip">
            <strong>{data.site.name}</strong>
            {anyFake && <span className="badge">SOME FAKE DATA</span>}
          </div>

          {picking && view !== 'hud' && <div className="map-hint">Click the map to set point {picking === 'start' ? 'A (start)' : 'B (end)'}</div>}

          {readout && view !== 'hud' && (
            <div className="readout" aria-live="off">
              {readout.ll && (
                <span>
                  {fmtLat(readout.ll.lat)}, {fmtLon(readout.ll.lon)}
                </span>
              )}
              <span>
                height <b>{Math.round(readout.z)} m</b>
              </span>
              <span>
                slope <b>{Number.isFinite(readout.slope) ? readout.slope.toFixed(1) : '–'}°</b>
              </span>
              <span className={`haz h${readout.hazard}`}>{HAZ_WORD[readout.hazard]} ground</span>
              {readout.ti != null && Number.isFinite(readout.ti) && (
                <span>
                  thermal inertia <b>{Math.round(readout.ti)}</b>
                </span>
              )}
              {readout.mineral && <span>{readout.mineral}</span>}
              {readout.back != null && (
                <span>
                  <b>{Math.round(readout.back)} min</b> back to {mode === 'outing' ? 'rover' : 'A'}
                </span>
              )}
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
              (data.layers.find((l) => l.id === 'minerals')?.legend ?? []).map((e) => (
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
            {view !== 'hud' && ok && data.route && (
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
          </div>
        </div>
        {view === 'hud' && <HudView data={data} onPosition={setAstronaut} large={large} onLarge={setLarge} visor={visor} onVisor={setVisor} />}
      </main>
    </div>
  )
}

const fmtXY = (p) => `x ${Math.round(p.x)} m, y ${Math.round(p.y)} m`
const fmtLL = (ll) => `${fmtLat(ll.lat)}, ${fmtLon(ll.lon)}`
