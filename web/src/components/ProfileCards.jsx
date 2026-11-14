// The Efficient / Balanced / Safe cards both modes share. A computed route (planRoutes) shows distance,
// walk, risk and "needs X of usable" with routing's one-way budget; over budget is a warning. The Team
// outing demo (plan.json profiles, lib/teamOuting.js) shows routing's own numbers. A start inside a red zone
// shows its escape separately; the totals include it.
// escapeNote: routing's manifest.escape.note (the escape times are an emergency estimate).
export default function ProfileCards({ results, profiles, profile, setProfile, usableMin, escapeNote }) {
  if (!results) return null
  return (
    <div className="profiles" role="group" aria-label="Route mode">
      {profiles.map((p) => {
        const r = results[p.id]
        const bad = r.ok && r.plan.checks.some((c) => !c.ok && c.level !== 'warn')
        const over = r.ok && r.plan.over_budget
        return (
          <button key={p.id} className={`${profile === p.id ? 'active' : ''}${bad ? ' over' : over ? ' warn' : ''}`} aria-pressed={profile === p.id} onClick={() => setProfile(p.id)} disabled={!r.ok}>
            <b>{p.label}</b>
            {r.ok && !r.fromFile ? (
              <>
                <span>{(r.plan.exact.distance_m / 1000).toFixed(2)} km</span>
                <span>{r.plan.exact.walk_min.toFixed(1)} min walk</span>
                <span>{r.plan.exact.risk_min.toFixed(1)} min risky</span>
                {r.plan.escape && (
                  <span className="escape-line" title={escapeNote ?? undefined}>
                    escape {r.plan.escape.walk_min.toFixed(1)} min, {Math.round(r.plan.escape.distance_m)} m (estimate)
                  </span>
                )}
                <span>
                  needs {Math.round(r.plan.needed_min)} of {usableMin ?? r.plan.budgets.usable_min} min
                </span>
                {over && <em className="warn">over budget</em>}
                {bad && <em>over a limit</em>}
              </>
            ) : r.ok ? (
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
  )
}
