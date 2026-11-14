// The helmet HUD and the "simulate EVA" demo (Person 5).
// Reads data.plan, data.waypoints, data.route and the radiation table (CONTRACT.md).
// The maths is in sim.js. Oxygen and battery are not in the contract: they are
// simulated from the EVA time limit in plan.json (see sim.js for the assumptions).
//
// Keys: space = play or pause, S = solar storm, R = reset.

import { useEffect, useMemo, useRef, useState } from 'react'
import './hud.css'
import {
  BATTERY_MIN_PER_EVA,
  buildTimeline,
  cardinal,
  clock,
  doseRate,
  doseTotal,
  localClock,
  DUST_WARN_TAU,
  parseTable,
  spaceWeatherModel,
  radiationModel,
  stateAt,
  startStorm,
  stopList,
  trackAt,
  trailUntil,
  weatherModel,
  START_LOCAL_HOUR,
} from './sim.js'

const SIM_MIN_PER_SECOND = 6 // speed 1x: six EVA minutes per real second
const SPEEDS = [1, 3, 6]

const PHASE_TEXT = {
  walk: 'WALKING',
  stop: 'SAMPLING',
  return: 'STORM: RETURNING',
  done: 'AT LANDING',
}

function Compass({ heading }) {
  const ticks = Array.from({ length: 24 }, (_, i) => i * 15)
  return (
    <svg className="hud-compass" viewBox="-64 -64 128 128" role="img" aria-label={`Heading ${Math.round(heading)} degrees`}>
      <g className="dial" style={{ transform: `rotate(${-heading}deg)` }}>
        <circle r="54" className="ring" />
        {ticks.map((a) => (
          <line key={a} y1="-54" y2={a % 90 === 0 ? -49 : a % 45 === 0 ? -50 : -52} transform={`rotate(${a})`} />
        ))}
        {[['N', 0], ['E', 90], ['S', 180], ['W', 270]].map(([l, a]) => (
          <text key={l} className={l === 'N' ? 'north' : ''} transform={`rotate(${a}) translate(0,-41) rotate(${heading - a})`}>
            {l}
          </text>
        ))}
      </g>
      <polygon className="pointer" points="0,-54 -5,-63 5,-63" />
      <text className="deg" y="-3">{Math.round(heading)}°</text>
      <text className="card" y="12">{cardinal(heading)}</text>
    </svg>
  )
}

function Gauge({ label, pct, value, low }) {
  const p = Math.max(0, Math.min(100, pct))
  return (
    <div className="hud-gauge">
      <div className="hud-gauge-top">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="hud-bar" role="progressbar" aria-valuenow={Math.round(p)} aria-valuemin="0" aria-valuemax="100" aria-label={label}>
        <div className={low ? 'low' : ''} style={{ width: `${p}%` }} />
      </div>
    </div>
  )
}

const GROUND = ['Go', 'Careful', 'No-go']

// Height along the whole route with a dot where the crew is (from the planner's track).
function ElevationProfile({ track, d }) {
  const w = 300
  const h = 56
  const d1 = track[track.length - 1].distance_m || 1
  const lo = Math.min(...track.map((r) => r.elev_m))
  const hi = Math.max(...track.map((r) => r.elev_m))
  const x = (m) => (m / d1) * w
  const y = (e) => h - 6 - ((e - lo) / (hi - lo || 1)) * (h - 12)
  const here = trackAt({ track }, d)
  return (
    <svg className="hud-profile" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Height along the route">
      <polyline points={track.map((r) => `${x(r.distance_m).toFixed(1)},${y(r.elev_m).toFixed(1)}`).join(' ')} />
      <circle cx={x(d)} cy={y(here.elev)} r="4" />
    </svg>
  )
}

function MiniMap({ tl, extent, pos, waypoints, trail, nextId, storm, stormPath }) {
  const [w, h] = extent
  const pt = (c) => `${c[0]},${h - c[1]}`
  const stopNumber = {}
  let n = 0
  for (const f of waypoints.features) if (f.properties.kind === 'stop') stopNumber[f.properties.id] = ++n
  return (
    <svg className="hud-mini" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Route and astronaut position">
      {[1, 2, 3].map((i) => (
        <g key={i} className="grid">
          <line x1={(w / 4) * i} y1="0" x2={(w / 4) * i} y2={h} />
          <line x1="0" y1={(h / 4) * i} x2={w} y2={(h / 4) * i} />
        </g>
      ))}
      <polyline points={tl.pts.map(pt).join(' ')} className="route" />
      {stormPath && <polyline points={stormPath.map(pt).join(' ')} className="stormpath" />}
      <polyline points={trail.map(pt).join(' ')} className={storm ? 'trail storm' : 'trail'} />
      {waypoints.features.map((f) => {
        if (f.properties.kind === 'rover') return null // there is no rover: home is the plan's start
        const [x, y] = f.geometry.coordinates
        const home = f.properties.id === tl.roverId
        const label = home ? (f.properties.name?.[0] ?? 'S').toUpperCase() : stopNumber[f.properties.id] ?? ''
        return (
          <g key={f.properties.id} className={f.properties.id === nextId ? 'next' : ''}>
            <circle cx={x} cy={h - y} r={home ? 60 : 55} className={home ? 'home' : 'stop'} />
            <text x={x} y={h - y} className="label">{label}</text>
          </g>
        )
      })}
      <circle cx={pos.x} cy={h - pos.y} r="48" className={storm ? 'me storm' : 'me'} />
    </svg>
  )
}

// onPosition(p) tells the main map where the astronaut is (null when the HUD closes).
// large and onLarge switch the big-text projector mode, which the app also uses to widen the panel.
// visor and onVisor switch the full-screen visor view (the app hides its sidebar and floats the HUD over the map).
export default function HudView({ data, onPosition, large, onLarge, visor, onVisor }) {
  const { plan, waypoints, route } = data
  const tl = useMemo(() => buildTimeline(plan, waypoints, route), [plan, waypoints, route])

  // Radiation and weather tables are optional: the HUD still works without them.
  const [rad, setRad] = useState(null)
  const [wx, setWx] = useState(null)
  const [sw, setSw] = useState(null)
  useEffect(() => {
    const load = (file, make, set) => {
      if (!file) return set(null)
      fetch(`./${file}`)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status))))
        .then((text) => set(make(parseTable(text))))
        .catch(() => set(null))
    }
    load(data.tables?.radiation, radiationModel, setRad)
    load(data.tables?.weather, weatherModel, setWx)
    if (data.tables?.space_weather) {
      fetch(`./${data.tables.space_weather}`)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status))))
        .then((text) => setSw(spaceWeatherModel(text)))
        .catch(() => setSw(null))
    } else setSw(null)
  }, [data.tables])

  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(SPEEDS[1])
  const [storm, setStorm] = useState(null)
  const [compact, setCompact] = useState(false)

  // Advance the clock while playing. Keep the latest values in a ref so the timer is created once.
  const live = useRef({ tl, storm })
  live.current = { tl, storm }
  useEffect(() => {
    if (!playing) return undefined
    const id = setInterval(() => {
      setT((prev) => {
        const next = prev + (SIM_MIN_PER_SECOND * speed) / 10
        // Without a storm the walk ends at the planned total; after one it ends back at the start.
        return live.current.storm ? next : Math.min(next, live.current.tl.totalMin)
      })
    }, 100)
    return () => clearInterval(id)
  }, [playing, speed])

  const s = tl ? stateAt(tl, t, storm) : null
  const phase = s?.phase
  useEffect(() => {
    if (phase === 'done') setPlaying(false)
  }, [phase])

  const triggerStorm = () => {
    if (tl && !storm && phase !== 'done') setStorm(startStorm(tl, t, s.d))
  }
  const reset = () => {
    setPlaying(false)
    setStorm(null)
    setT(0)
  }
  const scrub = (value) => {
    setStorm(null) // jumping around the timeline cancels the storm
    setT(Number(value))
  }

  // Keyboard shortcuts for the live demo.
  const keys = useRef({})
  keys.current = { triggerStorm, reset, toggle: () => phase !== 'done' && setPlaying((p) => !p), large: () => onLarge?.(!large), visor: () => onVisor?.(!visor), exitVisor: () => onVisor?.(false) }
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|SELECT|BUTTON|TEXTAREA)$/.test(e.target.tagName)) return
      if (e.key === ' ') { e.preventDefault(); keys.current.toggle() }
      else if (e.key === 's' || e.key === 'S') keys.current.triggerStorm()
      else if (e.key === 'r' || e.key === 'R') keys.current.reset()
      else if (e.key === 'l' || e.key === 'L') keys.current.large()
      else if (e.key === 'v' || e.key === 'V') keys.current.visor()
      else if (e.key === 'Escape') keys.current.exitVisor()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const stops = useMemo(() => (tl ? stopList(tl) : []), [tl])
  const trail = useMemo(() => (tl ? trailUntil(tl, t, storm) : []), [tl, Math.floor(t / 2), storm]) // eslint-disable-line react-hooks/exhaustive-deps

  // Show the astronaut on the main map too.
  const sx = s?.x
  const sy = s?.y
  const stormOn = !!storm
  useEffect(() => {
    if (sx !== undefined) onPosition?.({ x: sx, y: sy, storm: stormOn, trail })
  }, [sx, sy, stormOn, trail]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onPosition?.(null), []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!plan || !waypoints || !tl) {
    return (
      <div className="hud hud-scroll">
        <p className="hud-title">HUD</p>
        <p>Needs plan.json and waypoints.geojson.</p>
      </div>
    )
  }

  const eva = plan.budgets?.eva_max_min ?? tl.totalMin
  const oxygen = 100 - (t / eva) * 100
  const battery = 100 - (t / (eva * BATTERY_MIN_PER_EVA)) * 100
  const rate = rad ? doseRate(rad, t, storm) : null
  const dose = rad ? doseTotal(rad, t, storm) : null
  const limit = plan.budgets?.radiation_limit_usv
  const stormNow = !!storm && phase !== 'done'
  const cond = wx ? wx.at(START_LOCAL_HOUR + t / 60) : null
  const ground = storm?.ret ? null : trackAt(tl, s.d) // off the route during a planned storm return

  // Stop status: sampled once its time has passed, unless a storm cut the outing short.
  const cutoff = storm ? storm.t : t
  const status = (seg) => (seg.t1 <= cutoff ? 'done' : seg.t0 <= cutoff && !storm ? 'now' : 'todo')
  const here = stops.find((seg) => status(seg) === 'now')
  const here_wp = here && waypoints.features.find((f) => f.properties.id === here.to)
  const nextId = phase === 'done' ? tl.roverId : s.nextId
  const sampled = stops.filter((seg) => seg.t1 <= cutoff).length

  const alerts = []
  if (storm && phase === 'done') alerts.push({ level: 'amber', text: `Sheltering in ${tl.roverName} until the storm passes.` })
  else if (storm) alerts.push({ level: 'red', text: `SOLAR STORM. Return to ${tl.roverName} now.` })
  else if (rad && rate > rad.baseline * 2) alerts.push({ level: 'red', text: 'Radiation rising. Head for shelter.' })
  if (limit && dose > limit * 0.8) alerts.push({ level: 'red', text: 'Dose near the mission limit.' })
  if (phase !== 'done') {
    if (t + s.shelterMin > eva) alerts.push({ level: 'red', text: 'Not enough time left to walk back.' })
    else if (t + s.shelterMin > eva * 0.85) alerts.push({ level: 'amber', text: 'Turn back soon: time limit close.' })
  }
  if (cond?.dust > DUST_WARN_TAU) alerts.push({ level: 'amber', text: 'Heavy dust: poor visibility and less solar power.' })
  if (oxygen < 20) alerts.push({ level: 'red', text: 'Oxygen low.' })
  if (battery < 20) alerts.push({ level: 'amber', text: 'Battery low.' })
  if (!alerts.length) alerts.push({ level: 'green', text: 'All systems normal.' })

  return (
    <section className={`hud${stormNow ? ' alarm' : ''}${large ? ' large' : ''}`} aria-label="Helmet HUD">
      <div className="hud-scroll">
      <div className="hud-head">
        <span className={`hud-phase ${phase}`}>{PHASE_TEXT[phase]}</span>
        <span className="hud-clock">
          EVA {clock(t)} · local {localClock(t)}
        </span>
        <button className={`hud-toggle wide${visor ? ' on' : ''}`} onClick={() => onVisor?.(!visor)} aria-pressed={!!visor} title="Full-screen visor view (V, Esc to leave)">
          {visor ? 'Exit visor' : 'Visor'}
        </button>
        <button className={`hud-toggle${large ? ' on' : ''}`} onClick={() => onLarge?.(!large)} aria-pressed={!!large} title="Large text for a projector (L)">
          Aa
        </button>
        <button className="hud-toggle" onClick={() => setCompact((c) => !c)} aria-label={compact ? 'Expand HUD' : 'Shrink HUD'}>
          {compact ? '+' : '–'}
        </button>
      </div>

      {!compact && (
        <>
          <div className="hud-row">
            <Compass heading={s.heading} />
            <MiniMap tl={tl} extent={data.site.extent_m} pos={s} waypoints={waypoints} trail={trail} nextId={nextId} storm={!!storm} stormPath={storm?.ret?.pts} />
          </div>
        </>
      )}

      <div className="hud-grid">
        <div>
          <div className="hud-small">{phase === 'done' ? 'Arrived' : `Next: ${s.nextName}`}</div>
          <div className="hud-big">{Math.round(s.nextDist)} m</div>
        </div>
        <div>
          <div className="hud-small">Back to shelter</div>
          <div className="hud-big">{Math.ceil(s.shelterMin)} min</div>
        </div>
      </div>

      <p className="hud-pace">
        {s.pace > 0 ? (
          <>
            Pace <b>{Math.round(s.pace)} m/min</b> · {((s.pace * 60) / 1000).toFixed(1)} km/h
          </>
        ) : (
          'Pace: stopped'
        )}
        {plan.mobility?.note && <span> · {plan.mobility.note}</span>}
      </p>

      {here_wp && (
        <div className="hud-card">
          <strong>{here_wp.properties.name}</strong>
          <span>{here_wp.properties.why}</span>
        </div>
      )}

      <Gauge label="Oxygen" pct={oxygen} value={`${Math.round(oxygen)}%`} low={oxygen < 20} />
      <Gauge label="Battery" pct={battery} value={`${Math.round(battery)}%`} low={battery < 20} />
      {rad && (
        <Gauge
          label={`Radiation (est.) ${Math.round(rate)} µSv/h`}
          pct={limit ? (dose / limit) * 100 : 0}
          value={limit ? `${Math.round(dose)} / ${limit} µSv` : `${Math.round(dose)} µSv`}
          low={rate > rad.baseline * 2}
        />
      )}

      {ground && (
        <>
          <div className="hud-weather" aria-label="Ground under the crew">
            <div>
              <span className="hud-small">Slope</span>
              <b>{Math.round(ground.slope)}°</b>
            </div>
            <div>
              <span className="hud-small">Height</span>
              <b>{Math.round(ground.elev)} m</b>
            </div>
            <div>
              <span className="hud-small">Ground</span>
              <b>{GROUND[ground.hazard] ?? 'Go'}</b>
            </div>
          </div>
          <ElevationProfile track={tl.track} d={s.d} />
        </>
      )}

      {cond && (
        <div className="hud-weather" aria-label="Conditions">
          <div>
            <span className="hud-small">Temp</span>
            <b>{Math.round(cond.temp)} °C</b>
          </div>
          {cond.pressure != null && (
            <div>
              <span className="hud-small">Pressure</span>
              <b>{Math.round(cond.pressure)} Pa</b>
            </div>
          )}
          {cond.dust != null && (
            <div>
              <span className="hud-small">Dust τ</span>
              <b>{cond.dust.toFixed(1)}</b>
            </div>
          )}
        </div>
      )}

      {sw && (
        <p className="hud-realstorm">
          <span className="hud-small">Real NASA storm data (DONKI)</span>
          <b>
            {sw.fastest.kms} km/s CME, {sw.fastest.start_utc.slice(0, 10)}
          </b>
          <span>
            Expected at Mars {sw.fastest.mars_arrival_utc.slice(0, 10)}. {sw.hits} such events in this file.{' '}
            <a href={sw.fastest.link} target="_blank" rel="noreferrer">Source</a>
          </span>
        </p>
      )}

      {t === 0 && !playing && (
        <p className="hud-hint">Press Simulate EVA to watch the crew walk the route. Press Solar storm to see them switch to the return route.</p>
      )}

      <ul className="hud-alerts" aria-live="polite">
        {alerts.map((a) => (
          <li key={a.text} className={a.level}>
            {a.text}
          </li>
        ))}
      </ul>

      {!compact && (
        <ol className="hud-stops" aria-label="Science stops">
          {stops.map((seg) => (
            <li key={seg.to} className={status(seg)}>
              <span className="dot" />
              {seg.toName}
            </li>
          ))}
        </ol>
      )}

      {phase === 'done' && (
        <div className="hud-summary">
          <strong>{storm ? 'Storm return complete' : 'EVA complete'}</strong>
          <span>
            {sampled} of {stops.length} stops sampled · {clock(t)} outside
            {dose != null && ` · ${Math.round(dose)} µSv`}
          </span>
        </div>
      )}

      </div>

      <div className="hud-foot">
      <div className="hud-controls">
        <button onClick={() => setPlaying((p) => !p)} disabled={phase === 'done'}>
          {phase === 'done' ? 'Finished' : playing ? 'Pause' : t > 0 ? 'Resume' : 'Simulate EVA'}
        </button>
        <button onClick={triggerStorm} disabled={!!storm || phase === 'done'} className="storm">
          Solar storm
        </button>
        <button onClick={reset}>Reset</button>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Speed">
          {SPEEDS.map((v) => (
            <option key={v} value={v}>
              {v}x
            </option>
          ))}
        </select>
      </div>
      <input
        type="range"
        min="0"
        max={tl.totalMin}
        step="1"
        value={Math.min(t, tl.totalMin)}
        onChange={(e) => scrub(e.target.value)}
        aria-label="EVA time"
      />
      <p className="hud-note">Keys: space play, S storm, R reset, L large text, V visor. {tl.track && 'Slope, height, time back and the storm return come from the route planner. '}Oxygen and battery are simulated from the EVA time limit. Radiation is an estimate, not a Jezero measurement.</p>
      </div>
    </section>
  )
}
