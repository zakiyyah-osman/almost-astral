// What to tell the crew when a route cannot be found (planOuting's { ok: false, reason, reason_text,
// from, to, leg }), and a key for that failure so the pop-up opens once per new failure, not on
// every render.

// The point the route could not reach, in words.
export function pointName(to) {
  if (!to) return 'the next point'
  if (to.id === 'dest') return `the destination${to.name ? ` (${to.name})` : ''}`
  if (/^q\d+$/.test(to.id ?? '')) return `side quest ${to.id.slice(1)}${to.name ? ` (${to.name})` : ''}`
  return to.name ?? to.id
}

export function unreachableText(r) {
  if (r.reason === 'escape_unavailable' || r.reason === 'no_exit' || r.reason === 'start_too_steep') return `No walking route from the start: ${r.reason_text}.`
  if (r.reason === 'landing_blocked') return `No walking route from ${r.from?.name ?? 'the start'}: ${r.reason_text}.`
  return `No walking route to ${pointName(r.to)}: ${r.reason_text ?? 'no path'}.`
}

// { key, title, messages: [{ reason, title, detail }] } for a failed result, or null when it did not fail.
export function routeFailure(r) {
  if (!r || r.ok !== false) return null
  const at = (p) => (p ? `${Math.round(p.x)},${Math.round(p.y)}` : '-')
  const key = `${r.reason}|${r.from?.id}@${at(r.from)}|${r.to?.id}@${at(r.to)}`
  const where = r.reason === 'landing_blocked' ? r.from?.name ?? 'The start' : pointName(r.to)
  const blocked = typeof r.reason === 'number' && r.reason >= 1 && r.reason <= 5
  const detail = blocked
    ? `${where[0].toUpperCase()}${where.slice(1)} is on a cell the crew may not enter: ${r.reason_text}. Pick a point nearby that is not blocked.`
    : unreachableText(r)
  const zone = r.reason === 'escape_unavailable' || r.reason === 'no_exit' || r.reason === 'start_too_steep'
  const text = zone ? `No walking route from the start: ${r.reason_text}.` : detail
  return { key, title: 'No walking route', messages: [{ reason: String(r.reason), title: zone ? 'Inside a red zone' : blocked ? 'Blocked point' : 'Cannot be reached', detail: text }] }
}
