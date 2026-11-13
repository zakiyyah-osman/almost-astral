import { useEffect, useState } from 'react'
import SiteMap from './components/SiteMap.jsx'
import HudView from './hud/HudView.jsx'
import { loadData } from './lib/loadData.js'
import { checkRoute } from './lib/routeCheck.js'
import MissionCard from './components/MissionCard.jsx'

// hazard.png draws red and yellow; green cells are see-through, so green here just means "no overlay".
const HAZARD_KEY = [
  ['var(--ok)', 'Fine to walk'],
  ['#f0be28', 'Careful'],
  ['#dc3232', 'Do not enter'],
]

// One-click sets of layers: the ones that exist in layers.json are switched on, the rest off.
// 'base' stands for the real HiRISE image when there is one, and the shaded relief otherwise.
const PRESETS = [
  { id: 'safety', label: 'Safety', hint: 'Hazards on terrain', on: ['base', 'hazard'] },
  { id: 'science', label: 'Science', hint: 'Minerals on terrain', on: ['base', 'minerals'] },
  { id: 'ground', label: 'Ground', hint: 'Slope and thermal', on: ['base', 'slope', 'thermal'] },
]
const presetIds = (preset, ids) => preset.on.map((id) => (id === 'base' ? (ids.includes('hirise') ? 'hirise' : 'relief') : id))

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
  const [safety, setSafety] = useState(null) // the route checked against the hazard image
  const visor = visorOn && view === 'hud'

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        const ids = d.layers.map((l) => l.id)
        const start = presetIds(PRESETS[0], ids) // open on the Safety view
        setLayerState(Object.fromEntries(d.layers.map((l) => [l.id, { on: start.includes(l.id), opacity: l.opacity ?? 1 }])))
      })
      .catch((e) => setError(e.message))
  }, [])

  // Check the route against the hazard image ourselves, so a bad route shows up whoever made it.
  useEffect(() => {
    setSafety(null)
    const file = data?.layers.find((l) => l.id === 'hazard')?.file
    if (!file || !data.route) return
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        ctx.drawImage(img, 0, 0)
        setSafety(checkRoute(data.route, ctx.getImageData(0, 0, canvas.width, canvas.height), data.site.extent_m))
      } catch {
        setSafety(null)
      }
    }
    img.src = `./${file}`
  }, [data])

  const applyPreset = (preset) =>
    setLayerState((s) => {
      const on = presetIds(preset, Object.keys(s))
      return Object.fromEntries(Object.entries(s).map(([id, v]) => [id, { ...v, on: on.includes(id) }]))
    })
  const isPreset = (preset) => {
    const have = Object.keys(layerState)
    const on = presetIds(preset, have)
    return have.length > 0 && have.every((id) => !!layerState[id].on === on.includes(id))
  }

  const update = (id, patch) => setLayerState((s) => ({ ...s, [id]: { ...s[id], ...patch } }))

  if (error) return <p className="status">Could not load the data: {error}</p>
  if (!data) return <p className="status">Loading…</p>

  const plan = data.plan
  const features = data.waypoints?.features ?? []
  const names = Object.fromEntries(features.map((f) => [f.properties.id, f.properties.name]))
  const walkedM = plan ? plan.legs.reduce((s, l) => s + l.distance_m, 0) : 0
  const stopNumber = {}
  let n = 0
  for (const f of features) if (f.properties.kind === 'stop') stopNumber[f.properties.id] = ++n
  const stop = features.find((f) => f.properties.id === selectedStop)
  const anyFake = data.layers.some((l) => l.source.startsWith('FAKE'))

  return (
    <div className={`app${visor ? ' visor' : ''}`}>
      <MissionCard data={data} safety={safety} />
      <aside className="sidebar">
        <header className="brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <h1>Martian Map</h1>
            <p className="muted">Almost Astral · NASA Space Apps</p>
          </div>
        </header>

        <div className="views" role="group" aria-label="View">
          <button className={view === 'planning' ? 'active' : ''} aria-pressed={view === 'planning'} onClick={() => setView('planning')}>
            Planning
          </button>
          <button className={view === 'hud' ? 'active' : ''} aria-pressed={view === 'hud'} onClick={() => setView('hud')}>
            HUD
          </button>
        </div>

        {plan && (
          <section>
            <h2>Plan</h2>
            <div className="plan">
              <div className="stats">
                <div>
                  <b>{plan.totals.total_min} min</b>
                  <span>Outing</span>
                </div>
                <div>
                  <b>{(walkedM / 1000).toFixed(1)} km</b>
                  <span>Walk</span>
                </div>
                <div>
                  <b>{plan.radiation_dose_usv} µSv</b>
                  <span>Dose</span>
                </div>
              </div>
              {plan.budgets?.eva_max_min && (
                <div className="budget-wrap">
                  <div className="budget" title={`${plan.totals.total_min} of ${plan.budgets.eva_max_min} min allowed`}>
                    <div style={{ width: `${Math.min(100, (plan.totals.total_min / plan.budgets.eva_max_min) * 100)}%` }} />
                  </div>
                  <small>
                    {plan.totals.total_min} of {plan.budgets.eva_max_min} min allowed
                  </small>
                </div>
              )}
              {safety && (
                <p className={`route-check ${safety.redM > 1 ? 'bad' : safety.yellowM > 0.05 * safety.totalM ? 'warn' : 'ok'}`}>
                  {safety.redM > 1
                    ? `Warning: ${Math.round(safety.redM)} m of the route crosses no-go ground.`
                    : `Route check: stays out of every no-go cell. ${Math.round((safety.safeM / safety.totalM) * 100)}% on clear ground${safety.yellowM > 1 ? `, ${Math.round(safety.yellowM)} m over careful ground` : ''}.`}
                </p>
              )}
              <button className="print-btn" onClick={() => window.print()}>
                Print mission card
              </button>
              <ul className="legs">
                {plan.legs.map((leg) => (
                  <li key={`${leg.from}-${leg.to}`}>
                    <span>
                      {names[leg.from] ?? leg.from} → {names[leg.to] ?? leg.to}
                    </span>
                    <span>
                      {leg.distance_m} m · {leg.walk_min} min
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}

        {features.length > 0 && (
          <section>
            <h2>Stop</h2>
            {stop ? (
              <div className="stop-card">
                <div className="stop-head">
                  <span className={`pin${stop.properties.kind === 'rover' ? ' rover' : ''}`}>
                    {stop.properties.kind === 'rover' ? 'R' : stopNumber[stop.properties.id]}
                  </span>
                  <strong>{stop.properties.name}</strong>
                  <button onClick={() => setSelectedStop(null)} aria-label="Close stop">
                    ×
                  </button>
                </div>
                <p>{stop.properties.why}</p>
                <p className="muted">
                  x {stop.geometry.coordinates[0]} m · y {stop.geometry.coordinates[1]} m
                </p>
                <div className="photo">
                  {stop.properties.photo ? `Photo: ${stop.properties.photo}` : 'Photo to add (mission/photos/)'}
                </div>
              </div>
            ) : (
              <p className="muted">Click a numbered stop on the map to see what is there.</p>
            )}
          </section>
        )}

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
            {data.layers.map((l) => {
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
                    <button
                      className="info"
                      onClick={() => setOpenSource((s) => ({ ...s, [l.id]: !s[l.id] }))}
                      aria-expanded={open}
                      aria-label={`Source of ${l.title}`}
                      title="Where this data comes from"
                    >
                      i
                    </button>
                  </div>
                  {open && <p className="source">{fake ? l.source.replace(/^FAKE\s*/, 'Fake data ') : l.source}</p>}
                  {on && (
                    <label className="opacity">
                      Opacity
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={layerState[l.id]?.opacity ?? 1}
                        onChange={(e) => update(l.id, { opacity: Number(e.target.value) })}
                        aria-label={`${l.title} opacity`}
                      />
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
            layerState={layerState}
            selectedStop={selectedStop}
            onSelectStop={setSelectedStop}
            astronaut={view === 'hud' ? astronaut : null}
            layoutKey={`${view}-${large}-${visor}`}
          />

          <div className="map-chip">
            <strong>{data.site.name}</strong>
            {anyFake && <span className="badge">FAKE DATA</span>}
          </div>

          <div className="map-legend" aria-label="Map key">
            {layerState.hazard?.on && HAZARD_KEY.map(([colour, label]) => (
              <div key={label}>
                <i style={{ background: colour }} />
                {label}
              </div>
            ))}
            {data.route && (
              <div>
                <i className="line" />
                Planned route
              </div>
            )}
            {features.length > 0 && (
              <div>
                <i className="dot" />
                Stop
                <i className="dot rover" />
                Rover
              </div>
            )}
          </div>
        </div>
        {view === 'hud' && <HudView data={data} onPosition={setAstronaut} large={large} onLarge={setLarge} visor={visor} onVisor={setVisor} />}
      </main>
    </div>
  )
}
