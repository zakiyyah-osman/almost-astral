import Tag from './Tag.jsx'

// The three route modes side by side, with the real numbers of each route, how each mode chooses,
// and every input the numbers come from.
const ROWS = [
  { id: 'dist', label: 'Distance', get: (p) => p.legs.reduce((s, l) => s + l.distance_m, 0), fmt: (v) => `${(v / 1000).toFixed(2)} km`, better: 'low' },
  { id: 'walk', label: 'Walking time', get: (p) => p.totals.walk_min, fmt: (v) => `${Math.round(v)} min`, better: 'low' },
  { id: 'total', label: 'Whole outing', get: (p) => p.totals.total_min, fmt: (v) => `${Math.round(v)} min`, better: 'low', note: 'Walking, time on site and getting back into the rover' },
  { id: 'risk', label: 'Risky minutes', get: (p) => p.risk_min, fmt: (v) => `${v.toFixed(1)} min`, better: 'low', note: 'Minutes on careful ground or near no-go ground, weighted by how close' },
  { id: 'careful', label: 'On careful ground', get: (p) => p.metres_careful, fmt: (v) => `${Math.round(v)} m`, better: 'low' },
  { id: 'steep', label: 'Steepest slope', get: (p) => p.max_slope_deg, fmt: (v) => `${v.toFixed(1)}°`, better: 'low' },
  { id: 'climb', label: 'Climb / descent', get: (p) => p.ascent_m + p.descent_m, fmt: (v, p) => `${p.ascent_m} / ${p.descent_m} m`, better: 'low' },
  { id: 'dose', label: 'Radiation dose', get: (p) => p.radiation_dose_usv ?? NaN, fmt: (v) => (Number.isFinite(v) ? `${Math.round(v)} µSv` : '–'), better: 'low', tag: 'estimate' },
  { id: 'far', label: 'Furthest from shelter', get: (p, r) => r.furthest ?? NaN, fmt: (v) => (Number.isFinite(v) ? `${Math.round(v)} min` : '–'), better: 'low', note: 'The longest walk back to shelter from any point of the route' },
]

export default function ModeCompare({ results, profiles, profile, setProfile, params, inputs }) {
  if (!results) return <p className="muted">Set a route to compare the three modes.</p>
  const live = profiles.filter((p) => results[p.id]?.ok)
  const best = {}
  for (const row of ROWS) {
    const vals = live.map((p) => row.get(results[p.id].plan, results[p.id])).filter(Number.isFinite)
    if (vals.length > 1 && Math.max(...vals) - Math.min(...vals) > 1e-6) best[row.id] = Math.min(...vals)
  }
  return (
    <>
      <section>
        <h2>The three modes on this route</h2>
        <div className="compare-wrap">
          <table className="compare">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Measure</span>
                </th>
                {profiles.map((p) => (
                  <th key={p.id} scope="col" className={profile === p.id ? 'on' : ''}>
                    <button type="button" onClick={() => setProfile(p.id)} disabled={!results[p.id]?.ok} aria-pressed={profile === p.id}>
                      {p.label}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.id}>
                  <th scope="row" title={row.note}>
                    {row.label}
                    {row.tag && <Tag kind={row.tag} title={inputs.find((i) => i.id === 'dose')?.source} />}
                  </th>
                  {profiles.map((p) => {
                    const r = results[p.id]
                    if (!r?.ok) return <td key={p.id} className={profile === p.id ? 'on' : ''}>no route</td>
                    const v = row.get(r.plan, r)
                    const top = best[row.id] != null && Math.abs(v - best[row.id]) < 1e-6
                    return (
                      <td key={p.id} className={`${profile === p.id ? 'on' : ''}${top ? ' best' : ''}`}>
                        {row.fmt(v, r.plan)}
                      </td>
                    )
                  })}
                </tr>
              ))}
              <tr>
                <th scope="row">Within the limits</th>
                {profiles.map((p) => {
                  const r = results[p.id]
                  const bad = r?.ok ? r.plan.checks.filter((c) => !c.ok) : []
                  return (
                    <td key={p.id} className={`${profile === p.id ? 'on' : ''} ${r?.ok ? (bad.length ? 'fail' : 'pass') : ''}`} title={r?.ok ? r.plan.checks.map((c) => c.message).join(' ') : ''}>
                      {r?.ok ? (bad.length ? `No: ${bad.map((c) => c.id).join(', ')}` : 'Yes') : '–'}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="muted">The best value in each row is underlined. All three are calculated now, on this route, from the inputs below.</p>
      </section>

      <section>
        <h2>How each mode chooses</h2>
        <p className="muted">
          The route-finder adds up a cost for every 5 m step: <b className="formula">walking time × (1 + w × risk)</b>. Risk is {params.yellow_rate} on careful ground, plus up to {params.near_red_rate_max} more within {params.near_red_radius_m} m of no-go ground (more the closer it gets).
        </p>
        <ul className="mode-list">
          {profiles.map((p) => (
            <li key={p.id} className={profile === p.id ? 'on' : ''}>
              <b>{p.label}</b>
              <span>w = {params[p.key]}</span>
              <small>{params[p.key] === 0 ? 'Only walking time counts: the quickest route that stays within the hard limits.' : `A minute on risky ground costs as much as ${1 + params[p.key]} minutes on safe ground.`}</small>
            </li>
          ))}
        </ul>
        <p className="muted">
          Every mode keeps the same hard limits: never over {params.slope_max_deg}°, never on no-go ground or ground with no data, and at least {params.cliff_buffer_m} m from a drop.
        </p>
      </section>

      <section>
        <h2>What these numbers use</h2>
        <ul className="inputs">
          {inputs.map((i) => (
            <li key={i.id}>
              <span>
                <b>{i.name}</b>
                <small>{i.value}</small>
              </span>
              <Tag kind={i.kind} title={i.source} />
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
