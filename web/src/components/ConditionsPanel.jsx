import { useEffect, useState } from 'react'
import { parseTable, START_LOCAL_HOUR } from '../hud/sim.js'
import Tag from './Tag.jsx'

const W = 280
const H = 80
const PAD = { l: 34, r: 6, t: 6, b: 16 }

// Natural radiation on Earth, for comparison: about 2.4 mSv a year on average (UNSCEAR 2008), so 6.6 µSv a day.
const EARTH_USV_PER_DAY = 2400 / 365

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

// Solar events from DONKI that DONKI predicts will reach Mars, newest first.
function marsEvents(text) {
  const lines = String(text ?? '').trim().split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) return null
  const head = lines[0].split(',').map((h) => h.trim())
  const rows = lines.slice(1).map((line) => {
    const cells = line.split(',')
    return Object.fromEntries(head.map((h, i) => [h, (cells[i] ?? '').trim()]))
  })
  const hits = rows.filter((r) => r.mars_impact === 'True' && r.mars_arrival_utc).sort((a, b) => (a.start_utc < b.start_utc ? 1 : -1))
  return { total: rows.length, hits }
}

// Temperature, pressure, dust, dose rate and real solar events, with where each number comes from.
export default function ConditionsPanel({ data, plan }) {
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
        .then((t) => live && setSw(marsEvents(t)))
        .catch(() => {})
    }
    return () => {
      live = false
    }
  }, [data.tables])

  if (wx === undefined || rad === undefined) return null
  if (!wx && !rad && !sw) return null

  const outingMin = (plan?.totals?.total_min ?? 0) - (plan?.totals?.ingress_min ?? 0)
  const windowHours = [START_LOCAL_HOUR, START_LOCAL_HOUR + outingMin / 60]
  const max = (rows, f) => rows.reduce((m, r) => Math.max(m, r[f]), -Infinity)
  const min = (rows, f) => rows.reduce((m, r) => Math.min(m, r[f]), Infinity)
  const notes = data.sources_notes ?? {}
  const wxSource = notes['weather.csv']
  const radSource = notes['radiation.csv']
  const dust = wx?.rows.find((r) => Number.isFinite(r.dust_tau))?.dust_tau
  const press = wx?.rows.filter((r) => Number.isFinite(r.pressure_pa)).map((r) => r.pressure_pa)
  const radFlat = rad && max(rad.rows, 'dose_rate_usv_h') - min(rad.rows, 'dose_rate_usv_h') < 0.05
  const dose = plan?.radiation_dose_usv

  return (
    <section>
      <h2>Conditions</h2>
      {wx && (
        <>
          <p className="chart-title">
            Air temperature (°C), sol {wx.sol}{' '}
            {wxSource ? <Tag kind="real" title={wxSource} /> : <Tag kind="fake" title="weather.csv has no source in layers.json yet: treat it as a placeholder until the MEDA data is loaded" />}
          </p>
          <DayChart rows={wx.rows} field="temp_c" unit="Temperature" windowHours={windowHours} />
          <p className="muted">
            {min(wx.rows, 'temp_c').toFixed(0)} to {max(wx.rows, 'temp_c').toFixed(0)} °C
            {press?.length ? ` · pressure about ${Math.round(press.reduce((a, b) => a + b, 0) / press.length)} Pa` : ''}
            {dust !== undefined ? ` · dust opacity ${dust}` : ''}
          </p>
        </>
      )}
      {rad && (
        <>
          <p className="chart-title">
            Radiation dose rate (µSv/h) <Tag kind="estimate" title={radSource ?? 'radiation.csv'} />
          </p>
          {radFlat ? (
            <div className="big-number">
              <b>{rad.rows[0].dose_rate_usv_h.toFixed(1)}</b> µSv per hour, the same all day
            </div>
          ) : (
            <DayChart rows={rad.rows} field="dose_rate_usv_h" unit="Dose rate" windowHours={windowHours} />
          )}
          {dose != null && (
            <p className="muted">
              This outing: about <b>{dose} µSv</b>, the same as {(dose / EARTH_USV_PER_DAY).toFixed(0)} days of natural radiation on Earth{' '}
              <Tag kind="estimate" title="Earth average about 2.4 mSv a year (UNSCEAR 2008)" />.
            </p>
          )}
          <p className="muted">Modelled from Curiosity RAD figures at Gale, not measured here: Perseverance has no dose instrument.</p>
        </>
      )}
      <p className="muted">The shaded band is the outing, leaving at {START_LOCAL_HOUR}:00 local time (an assumption).</p>
      {sw && (
        <>
          <p className="chart-title">
            Solar storms that reached Mars <Tag kind="real" title={notes['space_weather.csv'] ?? 'NASA DONKI'} />
          </p>
          <p className="muted">
            NASA DONKI logged {sw.total} solar events in this file; DONKI predicts {sw.hits.length} reached Mars. The latest:
          </p>
          <ul className="events">
            {sw.hits.slice(0, 5).map((e) => (
              <li key={e.event_id}>
                <span>
                  {e.type} {e.detail && `· ${e.detail}`}
                </span>
                <span>
                  at Mars {e.mars_arrival_utc.slice(0, 10)}{' '}
                  {e.link && (
                    <a href={e.link} target="_blank" rel="noreferrer">
                      source
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
