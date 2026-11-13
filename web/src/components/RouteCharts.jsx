import { useEffect, useMemo, useState } from 'react'
import { buildTimeline, clock } from '../hud/sim.js'
import { readDem, routeProfile } from '../lib/profile.js'

const W = 280
const H = 90
const PAD = { l: 34, r: 6, t: 6, b: 16 }

const niceMax = (v) => {
  if (!(v > 0)) return 1
  const step = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / step) * step
}

// One small line chart. series: [{d, v}] with v possibly NaN (gaps). marks: distances along the path to draw as ticks.
function LineChart({ series, unit, marks, area, domain }) {
  const good = series.filter((p) => Number.isFinite(p.v))
  if (good.length < 2) return <p className="muted">No data along the route.</p>
  const dMax = series[series.length - 1].d || 1
  const lo = domain ? domain[0] : Math.min(...good.map((p) => p.v))
  const hi = domain ? domain[1] : Math.max(...good.map((p) => p.v))
  const span = hi - lo || 1
  const x = (d) => PAD.l + (d / dMax) * (W - PAD.l - PAD.r)
  const y = (v) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b)
  let path = ''
  let pen = false
  for (const p of series) {
    if (!Number.isFinite(p.v)) {
      pen = false
      continue
    }
    path += `${pen ? 'L' : 'M'}${x(p.d).toFixed(1)},${y(p.v).toFixed(1)}`
    pen = true
  }
  const base = H - PAD.b
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`Chart in ${unit} along the route`}>
      <line x1={PAD.l} x2={W - PAD.r} y1={base} y2={base} className="axis" />
      <text x={PAD.l - 4} y={PAD.t + 8} textAnchor="end" className="tick">{Math.round(hi)}</text>
      <text x={PAD.l - 4} y={base} textAnchor="end" className="tick">{Math.round(lo)}</text>
      <text x={PAD.l} y={H - 3} className="tick">0</text>
      <text x={W - PAD.r} y={H - 3} textAnchor="end" className="tick">{(dMax / 1000).toFixed(1)} km</text>
      {marks.map((m) => (
        <line key={m.id} x1={x(m.d)} x2={x(m.d)} y1={PAD.t} y2={base} className={m.rover ? 'mark rover' : 'mark'} />
      ))}
      {area && path && <path d={`${path}L${x(dMax)},${base}L${x(0)},${base}Z`} className="area" />}
      <path d={path} className="line-path" />
    </svg>
  )
}

// Elevation and slope along the route, then the outing timeline against the time allowance.
export default function RouteCharts({ data }) {
  const { plan, waypoints, route, site } = data
  const tl = useMemo(() => buildTimeline(plan, waypoints, route), [plan, waypoints, route])
  const [dem, setDem] = useState(undefined) // undefined = loading, null = not available

  useEffect(() => {
    let live = true
    fetch('./dem.tif')
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .then((buf) => live && setDem(buf ? readDem(buf) : null))
      .catch(() => live && setDem(null))
    return () => {
      live = false
    }
  }, [])

  const profile = useMemo(() => (dem && tl ? routeProfile(dem, site.extent_m, tl.pts, 10) : []), [dem, tl, site.extent_m])
  if (!tl) return null

  const marks = tl.segments
    .filter((s) => s.type === 'walk')
    .map((s) => ({ id: s.to, d: s.d1, rover: s.to === tl.roverId }))
  const maxMin = plan.budgets?.eva_max_min ?? Math.ceil(tl.totalMin)
  const axisMax = Math.max(maxMin, tl.totalMin)
  const slopeMax = Math.max(...profile.map((p) => p.slope).filter(Number.isFinite), 0)

  return (
    <>
      <section>
        <h2>Route profile</h2>
        {dem === undefined && <p className="muted">Loading terrain…</p>}
        {dem === null && <p className="muted">Profile not available: dem.tif is missing or in a format the app cannot read.</p>}
        {dem && (
          <>
            <p className="chart-title">Height (m)</p>
            <LineChart series={profile.map((p) => ({ d: p.d, v: p.z }))} unit="metres" marks={marks} area />
            <p className="chart-title">Slope (°)</p>
            <LineChart series={profile.map((p) => ({ d: p.d, v: p.slope }))} unit="degrees" marks={marks} domain={[0, niceMax(slopeMax)]} />
            <p className="muted">
              Along the planned route, from the terrain model. Slope is the rise over about 20 m, so it is smoother than the hazard
              map. Lines mark the stops and the rover.
            </p>
          </>
        )}
      </section>

      <section>
        <h2>Timeline</h2>
        <div className="timeline" role="img" aria-label={`Outing of ${Math.round(tl.totalMin)} minutes out of ${maxMin} allowed`}>
          {tl.segments.map((s, i) => (
            <div
              key={i}
              className={`seg ${s.type}`}
              style={{ left: `${(s.t0 / axisMax) * 100}%`, width: `${((s.t1 - s.t0) / axisMax) * 100}%` }}
              title={`${s.type === 'walk' ? 'Walk to' : 'Sample at'} ${s.toName}: ${Math.round(s.t1 - s.t0)} min`}
            />
          ))}
        </div>
        <div className="timeline-axis">
          <span>0</span>
          <span>{clock(maxMin)} allowed</span>
        </div>
        <p className="muted">
          <i className="swatch walk" /> Walking <i className="swatch stop" /> Sampling. Outing ends at T+{clock(tl.totalMin)}, leaving{' '}
          {Math.round(maxMin - tl.totalMin)} min spare.
        </p>
      </section>
    </>
  )
}
