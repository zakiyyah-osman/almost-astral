// Is a clicked point a safe place to land? Reads routing's landing export (landingData.js) and
// follows routing/docs/DESIGN.md sections 14.4-14.5 and manifest.message_templates:
//  - code 0 safe / 1 marginal: land where clicked
//  - codes 2-7: move to the centre of nearest_safe, a straight-line move (the lander comes down
//    from above), and say why, with the measured value at the CLICKED cell
//  - outside the window: nothing is chosen
// No threshold or text lives here: limits, names and sentences all come from the manifest.
import { cellOfXY, xyOfCell } from './landingData.js'

const MEASURES = ['pad_slope_deg', 'pad_roughness_m', 'pad_height_range_m', 'hazard_dist_m']
// The near_* tests of a marginal cell, in the manifest's order (message_templates.reasons['marginal (1)']).
const NEAR = ['near_too_steep', 'near_height_range', 'near_too_rough', 'near_hazard_or_clearance']

// {name} placeholders filled from vals; unknown names are left as they are.
const fill = (text, vals) => text.replace(/\{(\w+)\}/g, (m, k) => (vals[k] != null ? vals[k] : m))

// The four measured values at window cell i, as plain numbers (NaN where not computed).
export function measuredAt(g, i) {
  return Object.fromEntries(MEASURES.map((k) => [k, g.arrays[k] ? Number(g.arrays[k][i]) : NaN]))
}

// One message for a reason, filled per message_templates.rules.
export function messageFor(g, reason, measured, moved_m = 0) {
  const T = g.manifest.message_templates
  const t = T.templates[reason]
  if (!t) throw new Error(`landing export: no message template for ${reason}`)
  const vals = Object.fromEntries(Object.entries(T.fields).map(([k, v]) => [k, String(v)]))
  let detail = t.detail
  if (t.measure) {
    const v = measured?.[t.measure]
    vals.limit = String(t.limit)
    const noValue = !Number.isFinite(v) || (reason === 'hazard_or_clearance' && !(v < t.limit))
    if (noValue && t.detail_no_value) detail = t.detail_no_value
    else if (Number.isFinite(v)) vals.value = v.toFixed(t.decimals)
  }
  return { reason, code: t.code, title: t.title, detail: fill(detail, vals), moved_m }
}

// The reasons for a stored code from the files (message_templates.reasons): a failing cell's own
// code plus every other failure its measured values show, lowest code first; a marginal cell's
// near_* tests; 'safe' for code 0.
export function reasonsFor(g, code, measured) {
  const T = g.manifest.message_templates
  const name = (c) => g.manifest.safety_codes.find((s) => s.code === c)?.name
  if (code === 0) return ['safe']
  if (code === 1) {
    const pct = T.fields.marginal_pct / 100
    const near = NEAR.filter((r) => {
      const t = T.templates[r]
      const v = measured[t.measure]
      return r === 'near_hazard_or_clearance' ? v < (1 + pct) * t.limit : v > (1 - pct) * t.limit
    })
    return near.length ? near : ['marginal']
  }
  const out = new Set([name(code)])
  for (const r of ['hazard_or_clearance', 'too_steep', 'height_range', 'too_rough']) {
    const t = T.templates[r]
    const spec = g.manifest.grids[t.measure]
    const v = measured[t.measure]
    const fails = spec.fails_when === 'value < limit' ? v < spec.limit : v > spec.limit
    if (fails) out.add(r)
  }
  return [...out].filter(Boolean).sort((a, b) => T.templates[a].code - T.templates[b].code)
}

// The landing check for a click at (x, y) in site metres. Returns
// { status: 'safe' | 'marginal' | 'moved' | 'outside', code, code_name, click, cell, chosen, moved_m,
//   reasons, messages, moved_text, measured, warnings }.
// chosen is { x, y, row, col } (the click itself when safe or marginal), or null outside.
export function landingCheck(g, x, y) {
  const T = g.manifest.message_templates
  const click = { x, y }
  const cell = cellOfXY(g, x, y)
  if (!cell) {
    return { status: 'outside', code: null, code_name: null, click, cell: null, chosen: null, moved_m: 0, reasons: ['outside'], messages: [messageFor(g, 'outside', null)], moved_text: null, measured: null, warnings: [] }
  }
  const code = g.arrays.landing_safety[cell.i]
  const codeName = g.manifest.safety_codes.find((s) => s.code === code)?.name ?? `code ${code}`
  const measured = measuredAt(g, cell.i)
  const bits = g.arrays.landing_warn?.[cell.i] ?? 0
  const warnings = (g.manifest.warning_bits ?? []).filter((w) => bits & w.bit).map((w) => w.name)
  const reasons = reasonsFor(g, code, measured)
  let status = code === 0 ? 'safe' : code === 1 ? 'marginal' : 'moved'
  let chosen = { x, y, row: cell.row, col: cell.col }
  let moved = 0
  if (status === 'moved') {
    const row = g.arrays.nearest_safe[2 * cell.i]
    const col = g.arrays.nearest_safe[2 * cell.i + 1]
    const [cx, cy] = xyOfCell(g, row, col)
    chosen = { x: cx, y: cy, row, col }
    moved = Math.hypot(cx - x, cy - y)
  }
  const messages = reasons.map((r) => messageFor(g, r, measured, moved))
  const moved_text = status === 'moved' ? fill(T.moved, { moved_m: moved.toFixed(T.moved_decimals) }) : null
  return { status, code, code_name: codeName, click, cell, chosen, moved_m: moved, reasons, messages, moved_text, measured, warnings }
}
