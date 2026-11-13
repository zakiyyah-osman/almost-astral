import { buildTimeline, clock } from '../hud/sim.js'

// One printable page for the crew: stops with arrival times, limits and where every layer comes from.
// Hidden on screen and shown only when printing (see .mission-card in index.css).
export default function MissionCard({ data, safety }) {
  const { plan, waypoints, route, site } = data
  if (!plan || !waypoints) return null
  const tl = buildTimeline(plan, waypoints, route)
  const arrival = {}
  for (const s of tl?.segments ?? []) if (s.type === 'walk') arrival[s.to] = s.t1
  const stops = waypoints.features.filter((f) => f.properties.kind === 'stop')
  const rover = waypoints.features.find((f) => f.properties.kind === 'rover')
  const names = Object.fromEntries(waypoints.features.map((f) => [f.properties.id, f.properties.name]))
  const walkedM = plan.legs.reduce((s, l) => s + l.distance_m, 0)
  const fake = data.layers.some((l) => l.source.startsWith('FAKE'))

  return (
    <section className="mission-card" aria-label="Printable mission card">
      <h1>Mission card: {site.name}</h1>
      {fake && <p className="mc-fake">Some layers are still placeholder data. Do not use this card for a real outing.</p>}
      <p>
        Two crew walk out from {rover?.properties.name ?? 'the rover'} and back. Outing {plan.totals.total_min} min of{' '}
        {plan.budgets?.eva_max_min ?? '?'} allowed, walk {(walkedM / 1000).toFixed(1)} km, dose about {plan.radiation_dose_usv} µSv
        {plan.budgets?.radiation_limit_usv ? ` of ${plan.budgets.radiation_limit_usv} µSv allowed` : ''}.
      </p>

      <h2>Stops</h2>
      <table>
        <thead>
          <tr><th>#</th><th>Stop</th><th>Arrive</th><th>Why it matters</th></tr>
        </thead>
        <tbody>
          {stops.map((f, i) => (
            <tr key={f.properties.id}>
              <td>{i + 1}</td>
              <td>{f.properties.name}</td>
              <td>{arrival[f.properties.id] != null ? `T+${clock(arrival[f.properties.id])}` : ''}</td>
              <td>{f.properties.why}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Legs</h2>
      <table>
        <tbody>
          {plan.legs.map((l) => (
            <tr key={`${l.from}-${l.to}`}>
              <td>{names[l.from] ?? l.from} to {names[l.to] ?? l.to}</td>
              <td>{l.distance_m} m</td>
              <td>{l.walk_min} min</td>
            </tr>
          ))}
        </tbody>
      </table>

      {safety && (
        <p>
          Route check against the hazard map:{' '}
          {safety.redM > 1
            ? `WARNING, ${Math.round(safety.redM)} m of the route crosses no-go ground.`
            : `stays out of every no-go cell, ${Math.round((safety.safeM / safety.totalM) * 100)}% on clear ground.`}
        </p>
      )}

      <h2>Turn back if</h2>
      <ul>
        <li>A solar storm alert appears: stop sampling and take the shorter way back to the rover.</li>
        <li>The outing time, oxygen or battery reaches its limit, or a suit fault or injury happens.</li>
      </ul>

      <h2>Where the data comes from</h2>
      <ul>
        {data.layers.map((l) => (
          <li key={l.id}>
            {l.title}: {l.source}
          </li>
        ))}
      </ul>
      <p className="mc-note">
        Limits (outing time, dose), walking pace, oxygen and battery are our assumptions. Radiation at Jezero is an estimate from published
        Curiosity figures, not a Perseverance measurement.
      </p>
    </section>
  )
}
