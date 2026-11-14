// Recommended places to land or park the rover: flat, clear ground with short walks to the first
// and last science stops. Flatness limits are our assumptions, chosen to match the published
// human-landing criterion of slopes under about 5 degrees at 10 m scale (Golombek et al., LPSC 2021).
import { centreOf, cellOf } from './terrain.js'
import { timeField } from './pathfind.js'

export const LANDING_RULES = {
  radiusM: 50, // the pad: a circle of this radius must be flat and clear
  maxMeanSlopeDeg: 5, // average slope over the pad
  maxSlopeDeg: 10, // no cell on the pad steeper than this (the "careful" limit)
  minSeparationM: 250, // keep the suggestions apart so they are real alternatives
  minFromStopsM: 150, // do not land on top of a science stop (dust and exhaust)
  count: 3,
}

// Summed-area table for fast window sums.
function integral(values, width, height) {
  const s = new Float64Array((width + 1) * (height + 1))
  for (let r = 0; r < height; r++) {
    let row = 0
    for (let c = 0; c < width; c++) {
      row += values[r * width + c]
      s[(r + 1) * (width + 1) + c + 1] = s[r * (width + 1) + c + 1] + row
    }
  }
  return (r0, c0, r1, c1) => s[(r1 + 1) * (width + 1) + c1 + 1] - s[r0 * (width + 1) + c1 + 1] - s[(r1 + 1) * (width + 1) + c0] + s[r0 * (width + 1) + c0]
}

// Pad numbers around one cell, or null if the pad is not flat and clear.
export function padAt(cost, i, rules = LANDING_RULES, sums) {
  const { width, height, cellM } = cost
  const S = sums ?? padSums(cost, rules)
  const rc = Math.round(rules.radiusM / cellM)
  const r = Math.floor(i / width)
  const c = i % width
  if (r - rc < 0 || c - rc < 0 || r + rc >= height || c + rc >= width) return null
  const cells = (2 * rc + 1) ** 2
  const mean = S.slope(r - rc, c - rc, r + rc, c + rc) / cells
  const steep = S.steep(r - rc, c - rc, r + rc, c + rc)
  const blockedN = S.blocked(r - rc, c - rc, r + rc, c + rc)
  return { meanSlope: mean, steepCells: steep, blockedCells: blockedN, ok: mean <= rules.maxMeanSlopeDeg && steep === 0 && blockedN === 0 }
}

export function padSums(cost, rules = LANDING_RULES) {
  const { width, height, slope, blocked } = cost
  const s = new Float64Array(slope.length)
  const steep = new Float64Array(slope.length)
  const blk = new Float64Array(slope.length)
  for (let i = 0; i < slope.length; i++) {
    const v = Number.isFinite(slope[i]) ? slope[i] : 90
    s[i] = v
    steep[i] = v > rules.maxSlopeDeg ? 1 : 0
    blk[i] = blocked[i] ? 1 : 0
  }
  return { slope: integral(s, width, height), steep: integral(steep, width, height), blocked: integral(blk, width, height) }
}

// The best pads. stops: [{x, y}] in visiting order (first and last matter for the walk); avoid: every
// science stop, which a pad must stay minFromStopsM away from.
// Returns [{ x, y, meanSlope, walkFirstMin, walkLastMin, walkMin }] sorted by walking time.
export function recommendLanding(cost, stops, rules = LANDING_RULES, avoid = stops) {
  if (!stops?.length) return []
  const { width, height, cellM } = cost
  const first = cellOf(stops[0].x, stops[0].y, width, height, cellM)
  const last = cellOf(stops[stops.length - 1].x, stops[stops.length - 1].y, width, height, cellM)
  if (!first || !last) return []
  const tFirst = timeField(cost, first.i)
  const tLast = first.i === last.i ? tFirst : timeField(cost, last.i)
  const sums = padSums(cost, rules)
  const cand = []
  for (let i = 0; i < width * height; i++) {
    const walk = tFirst[i] + tLast[i]
    if (!Number.isFinite(walk)) continue
    const pad = padAt(cost, i, rules, sums)
    if (!pad?.ok) continue
    cand.push({ i, walk, meanSlope: pad.meanSlope, a: tFirst[i], b: tLast[i] })
  }
  cand.sort((p, q) => p.walk - q.walk || p.meanSlope - q.meanSlope)
  const out = []
  for (const k of cand) {
    const [x, y] = centreOf(k.i, width, height, cellM)
    if (avoid.some((s) => Math.hypot(s.x - x, s.y - y) < rules.minFromStopsM)) continue
    if (out.some((o) => Math.hypot(o.x - x, o.y - y) < rules.minSeparationM)) continue
    out.push({ x, y, meanSlope: k.meanSlope, walkFirstMin: k.a, walkLastMin: k.b, walkMin: k.walk })
    if (out.length >= rules.count) break
  }
  return out
}

// How a given spot (for example the current rover position) measures up against the pad rules.
export function judgeSpot(cost, x, y, rules = LANDING_RULES) {
  const cell = cellOf(x, y, cost.width, cost.height, cost.cellM)
  if (!cell) return null
  const pad = padAt(cost, cell.i, rules)
  return { slopeHere: cost.slope[cell.i], ...(pad ?? { ok: false, meanSlope: NaN }) }
}
