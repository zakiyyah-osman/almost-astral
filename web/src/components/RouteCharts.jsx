import { useMemo, useState } from 'react'
import { buildTimeline, clock, localClock } from '../hud/sim.js'
import Tag from './Tag.jsx'

const W = 280
const PAD = { l: 34, r: 6, t: 6, b: 16 }
const HAZ = ['var(--ok)', 'var(--warn)', 'var(--bad)']

const niceMax = (v) => {
  if (!(v > 0)) return 1
  const step = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / step) * step
}

// One small line chart along the route. series: [{d, v}]; marks: stops as numbered lines;
// limits: horizontal lines [{v, cls, label}]; strip: hazard class per sample, drawn under the axis.
function LineChart({ series, unit, marks, area, domain, limits = [], strip, hoverD, onHover, height = 90 }) {
  const H = height
  const good = series.filter((p) => Number.isFinite(p.v))
  if (good.length < 2) return <p className="muted">No data along the route.</p>
  const dMax = series[series.length - 1].d || 1
  const lo = domain ? domain[0] : Math.min(...good.map((p) => p.v))
  const hi = domain ? domain[1] : Math.max(...good.map((p) => p.v))
  const span = hi - lo || 1
  const base = H - PAD.b - (strip ? 6 : 0)
  const x = (d) => PAD.l + (d / dMax) * (W - PAD.l - PAD.r)
  const y = (v) => PAD.t + (1 - (v - lo) / span) * (base - PAD.t)
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
  const move = (e) => {
    if (!onHover) return
    const box = e.currentTarget.getBoundingClientRect()
    const d = Math.min(dMax, Math.max(0, (((e.clientX - box.left) / box.width) * W - PAD.l) / (W - PAD.l - PAD.r) * dMax))
    onHover(d)
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={`Chart in ${unit} along the route`} onPointerMove={move} onPointerDown={move} onPointerLeave={() => onHover?.(null)}>
      <line x1={PAD.l} x2={W - PAD.r} y1={base} y2={base} className="axis" />
      <text x={PAD.l - 4} y={PAD.t + 8} textAnchor="end" className="tick">{Math.round(hi)}</text>
      <text x={PAD.l - 4} y={base} textAnchor="end" className="tick">{Math.round(lo)}</text>
      <text x={PAD.l} y={H - 3} className="tick">0</text>
      <text x={W - PAD.r} y={H - 3} textAnchor="end" className="tick">{(dMax / 1000).toFixed(1)} km</text>
      {limits.map((l) => (
        <g key={l.v}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(l.v)} y2={y(l.v)} className={`limit ${l.cls}`} />
          <text x={W - PAD.r} y={y(l.v) - 2} textAnchor="end" className={`tick limit-label ${l.cls}`}>{l.label}</text>
        </g>
      ))}
      {marks.map((m) => (
        <g key={`${m.id}-${m.d}`}>
          <line x1={x(m.d)} x2={x(m.d)} y1={PAD.t} y2={base} className={m.rover ? 'mark rover' : 'mark'} />
          {m.label && <text x={x(m.d)} y={PAD.t + 6} textAnchor="middle" className="tick mark-label">{m.label}</text>}
        </g>
      ))}
      {area && path && <path d={`${path}L${x(dMax)},${base}L${x(0)},${base}Z`} className="area" />}
      <path d={path} className="line-path" />
      {strip &&
        series.slice(1).map((p, i) => (
          <rect key={i} x={x(series[i].d)} y={base + 1} width={Math.max(0.5, x(p.d) - x(series[i].d))} height={5} style={{ fill: HAZ[strip[i + 1]] ?? 'transparent' }} />
        ))}
      {hoverD != null && <line x1={x(hoverD)} x2={x(hoverD)} y1={PAD.t} y2={base} className="cursor" />}
    </svg>
  )
}

// Height, slope (with the limits), minutes back to the start and the hazard class along the active
// route, then the outing timeline against the time allowance. All from the active route.
export default function RouteCharts({ plan, waypoints, route, track, limits, onProbe, hazardNote }) {
  const tl = useMemo(() => buildTimeline(plan, waypoints, route), [plan, waypoints, route])
  const [hover, setHover] = useState(null)
  if (!tl) return null

  let stopNo = 0
  const marks = tl.segments
    .filter((s) => s.type === 'walk')
    .map((s) => ({ id: s.to, d: s.d1, rover: s.to === tl.roverId, label: s.to === tl.roverId ? 'R' : waypoints.features.find((f) => f.properties.id === s.to)?.properties.kind === 'stop' ? String(++stopNo) : 'B' }))
  const maxMin = plan.budgets?.eva_max_min ?? Math.ceil(tl.totalMin)
  const axisMax = Math.max(maxMin, plan.totals.total_min)
  const slopeMax = Math.max(...(track ?? []).map((p) => p.slope).filter(Number.isFinite), limits.red)
  const hoverPoint = hover != null && track?.length ? track.reduce((a, b) => (Math.abs(b.d - hover) < Math.abs(a.d - hover) ? b : a)) : null
  const setH = (d) => {
    setHover(d)
    if (d == null) onProbe?.(null)
    else if (track?.length) {
      const p = track.reduce((a, b) => (Math.abs(b.d - d) < Math.abs(a.d - d) ? b : a))
      onProbe?.({ x: p.x, y: p.y })
    }
  }

  let n = 0
  const segLabels = tl.segments.map((s) => (s.type === 'stop' ? String(++n) : ''))
  const hours = Array.from({ length: Math.floor(axisMax / 60) + 1 }, (_, h) => h)

  return (
    <>
      <section>
        <h2>Route profile</h2>
        {track?.length ? (
          <>
            <p className="chart-title">
              Height (m) <Tag kind="real" title="HiRISE terrain model (MRO), dem.tif" />
            </p>
            <LineChart series={track.map((p) => ({ d: p.d, v: p.z }))} unit="metres" marks={marks} area hoverD={hover} onHover={setH} />
            <p className="chart-title">
              Slope (°) and ground <Tag kind="calc" title={hazardNote} />
            </p>
            <LineChart
              series={track.map((p) => ({ d: p.d, v: p.slope }))}
              unit="degrees"
              marks={marks}
              domain={[0, niceMax(slopeMax)]}
              limits={[
                { v: limits.yellow, cls: 'warn', label: `${limits.yellow}° careful` },
                { v: limits.red, cls: 'bad', label: `${limits.red}° no-go` },
              ]}
              strip={track.map((p) => p.hazard)}
              hoverD={hover}
              onHover={setH}
              height={100}
            />
            <p className="chart-title">
              Minutes back to the start <Tag kind="calc" title="Fastest walk back from each point, plus the time to get into the rover, on the same terrain model" />
            </p>
            <LineChart series={track.map((p) => ({ d: p.d, v: p.back }))} unit="minutes" marks={marks} hoverD={hover} onHover={setH} domain={[0, niceMax(Math.max(...track.map((p) => p.back).filter(Number.isFinite), 10))]} height={70} />
            <p className="muted chart-readout" aria-live="polite">
              {hoverPoint
                ? `${Math.round(hoverPoint.d)} m along · height ${Math.round(hoverPoint.z)} m · slope ${hoverPoint.slope.toFixed(1)}° · ${['fine', 'careful', 'no-go'][hoverPoint.hazard]} ground · ${Math.round(hoverPoint.back)} min back`
                : 'Point at a chart to see the place on the map. The strip under the slope shows the ground: green fine, yellow careful, red no-go.'}
            </p>
          </>
        ) : (
          <p className="muted">The route profile needs the terrain model (dem.tif).</p>
        )}
      </section>

      <section>
        <h2>Timeline</h2>
        <div className="timeline" role="img" aria-label={`Outing of ${Math.round(plan.totals.total_min)} minutes out of ${maxMin} allowed`}>
          {tl.segments.map((s, i) => (
            <div key={i} className={`seg ${s.type}`} style={{ left: `${(s.t0 / axisMax) * 100}%`, width: `${((s.t1 - s.t0) / axisMax) * 100}%` }} title={`${s.type === 'walk' ? 'Walk to' : 'Sample at'} ${s.toName}: ${Math.round(s.t1 - s.t0)} min`}>
              {segLabels[i] && <span>{segLabels[i]}</span>}
            </div>
          ))}
          {plan.totals.ingress_min > 0 && (
            <div className="seg ingress" style={{ left: `${(tl.totalMin / axisMax) * 100}%`, width: `${(plan.totals.ingress_min / axisMax) * 100}%` }} title={`Back into the rover: ${plan.totals.ingress_min} min`} />
          )}
          {plan.budgets?.usable_min && <div className="usable" style={{ left: `${(plan.budgets.usable_min / axisMax) * 100}%` }} title={`Usable time: ${plan.budgets.usable_min} min`} />}
        </div>
        <div className="timeline-hours">
          {hours.map((h) => (
            <span key={h} style={{ left: `${((h * 60) / axisMax) * 100}%` }}>
              {h}h
              <small>{localClock(h * 60)}</small>
            </span>
          ))}
        </div>
        <p className="muted">
          <i className="swatch walk" /> Walking <i className="swatch stop" /> At a stop (numbered) <i className="swatch ingress" /> Into the rover. The thin line is the usable time
          ({plan.budgets?.usable_min} min: the {maxMin} min limit minus a {plan.budgets?.reserve_pct}% reserve). Ends at T+{clock(plan.totals.total_min)}, leaving{' '}
          {Math.round(maxMin - plan.totals.total_min)} min to the limit. Small times are local Mars time, leaving at 09:00 (an assumption).
        </p>
      </section>
    </>
  )
}
