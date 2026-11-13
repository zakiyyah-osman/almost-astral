import { useEffect, useState } from 'react'
import { parseTable, spaceWeatherModel, START_LOCAL_HOUR } from '../hud/sim.js'

const W = 280
const H = 80
const PAD = { l: 34, r: 6, t: 6, b: 16 }

// The rows of the sol with the most rows, sorted by hour.
function oneDay(rows, field) {
  const good = rows.filter((r) => Number.isFinite(r[field]) && Number.isFinite(r.sol))
  const counts = {}
  for (const r of good) counts[r.sol] = (counts[r.sol] ?? 0) + 1
  const sol = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a - b)[0]
  if (sol === undefined) return null
  return { sol: Number(sol), rows: good.filter((r) => r.sol === Number(sol)).sort((a, b) => a.local_hour - b.local_hour) }
}

// A line over one Mars day (0 to 24 local hours), with the outing window shaded.
function DayChart({ rows, field, unit, windowHours }) {
  const lo = Math.min(...rows.map((r) => r[field]))
  const hi = Math.max(...rows.map((r) => r[field]))
  const span = hi - lo || 1
  const x = (h) => PAD.l + (h / 24) * (W - PAD.l - PAD.r)
  const y = (v) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b)
  const path = rows.map((r, i) => `${i ? 'L' : 'M'}${x(r.local_hour).toFixed(1)},${y(r[field]).toFixed(1)}`).join('')
  const [a, b] = windowHours
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`${unit} through the day`}>
      <rect x={x(a)} y={PAD.t} width={Math.max(x(Math.min(b, 24)) - x(a), 0)} height={H - PAD.t - PAD.b} className="window" />
      <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="axis" />
      <text x={PAD.l - 4} y={PAD.t + 8} textAnchor="end" className="tick">{hi.toFixed(hi < 100 ? 1 : 0)}</text>
      <text x={PAD.l - 4} y={H - PAD.b} textAnchor="end" className="tick">{lo.toFixed(lo < 100 ? 1 : 0)}</text>
      {[0, 6, 12, 18, 24].map((h) => (
        <text key={h} x={x(h)} y={H - 3} textAnchor={h === 0 ? 'start' : h === 24 ? 'end' : 'middle'} className="tick">{h}h</text>
      ))}
      <path d={path} className="line-path" />
    </svg>
  )
}

// Temperature, pressure, dust, dose rate and real solar events, from the tables in layers.json.
export default function ConditionsPanel({ data }) {
  const [wx, setWx] = useState(undefined)
  const [rad, setRad] = useState(undefined)
  const [sw, setSw] = useState(null)

  useEffect(() => {
    let live = true
    const load = (file, set, pick) =>
      file
        ? fetch(`./${file}`)
            .then((r) => (r.ok ? r.text() : ''))
            .then((t) => live && set(pick(parseTable(t))))
            .catch(() => live && set(null))
        : set(null)
    load(data.tables?.weather, setWx, (rows) => oneDay(rows, 'temp_c'))
    load(data.tables?.radiation, setRad, (rows) => oneDay(rows, 'dose_rate_usv_h'))
    if (data.tables?.space_weather) {
      fetch(`./${data.tables.space_weather}`)
        .then((r) => (r.ok ? r.text() : ''))
        .then((t) => live && setSw(spaceWeatherModel(t)))
        .catch(() => {})
    }
    return () => {
      live = false
    }
  }, [data.tables])

  if (wx === undefined || rad === undefined) return null
  if (!wx && !rad) return null

  const outingH = (data.plan?.totals?.total_min ?? 0) / 60
  const windowHours = [START_LOCAL_HOUR, START_LOCAL_HOUR + outingH]
  const last = (rows, f) => rows.reduce((m, r) => Math.max(m, r[f]), -Infinity)
  const first = (rows, f) => rows.reduce((m, r) => Math.min(m, r[f]), Infinity)
  const dust = wx?.rows.find((r) => Number.isFinite(r.dust_tau))?.dust_tau
  const press = wx?.rows.filter((r) => Number.isFinite(r.pressure_pa)).map((r) => r.pressure_pa)
  const placeholder = data.plan?.fake || data.layers.some((l) => l.source.startsWith('FAKE'))

  return (
    <section>
      <h2>Conditions</h2>
      {wx && (
        <>
          <p className="chart-title">Air temperature (°C), sol {wx.sol}</p>
          <DayChart rows={wx.rows} field="temp_c" unit="Temperature" windowHours={windowHours} />
          <p className="muted">
            {first(wx.rows, 'temp_c').toFixed(0)} to {last(wx.rows, 'temp_c').toFixed(0)} °C
            {press?.length ? ` · pressure about ${Math.round(press.reduce((a, b) => a + b, 0) / press.length)} Pa` : ''}
            {dust !== undefined ? ` · dust opacity ${dust}` : ''}
          </p>
        </>
      )}
      {rad && (
        <>
          <p className="chart-title">Radiation dose rate (µSv/h), sol {rad.sol}</p>
          <DayChart rows={rad.rows} field="dose_rate_usv_h" unit="Dose rate" windowHours={windowHours} />
          <p className="muted">
            About {first(rad.rows, 'dose_rate_usv_h').toFixed(0)} to {last(rad.rows, 'dose_rate_usv_h').toFixed(0)} µSv/h. This is a modelled
            estimate from Curiosity RAD figures, not a measurement at this site.
          </p>
        </>
      )}
      <p className="muted">The shaded band is the outing, leaving at {START_LOCAL_HOUR}:00 local time (an assumption).</p>
      {sw && (
        <p className="muted">
          NASA DONKI logged {sw.total} solar events in the data window; {sw.hits} are predicted to reach Mars.
        </p>
      )}
      {placeholder && <p className="muted">Some values are still placeholders until the official data arrives.</p>}
    </section>
  )
}
