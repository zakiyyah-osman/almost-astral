// A custom mission: a start, any number of side quests, and a final destination (J0), with or
// without the walk back to the start. Pure maths on the cost grid from pathfind.js, so it runs in
// the browser and in tests.
import { planOuting } from './outing.js'
import { snapToFree, timeField } from './pathfind.js'
import { centreOf } from './terrain.js'

// The points of a mission in walking order, in the shape planOuting reads.
// mission: { start, quests: [], dest, back } where each point is { x, y, name, stopMin? }.
export function missionPoints(mission, defaultStopMin) {
  const { start, quests = [], dest, back } = mission
  if (!start || !dest) return null
  const pts = [{ id: 'start', kind: 'rover', name: start.name ?? 'Start', x: start.x, y: start.y }]
  quests.forEach((q, k) =>
    pts.push({ id: `q${k + 1}`, kind: 'stop', name: q.name ?? `Side quest ${k + 1}`, x: q.x, y: q.y, stopMin: q.stopMin ?? defaultStopMin, why: q.why ?? '', extra: { quest: true } }),
  )
  pts.push({ id: 'dest', kind: 'stop', name: dest.name ?? 'Destination', x: dest.x, y: dest.y, stopMin: dest.stopMin ?? (back ? defaultStopMin : 0), extra: { destination: true } })
  if (back) pts.push({ ...pts[0] })
  return pts
}

// What each side quest costs: the plan with it minus the plan without it, on the same profile.
// Returns [{ min, m, dose, risk }] in quest order, or null where the plan without it fails.
export function detourCosts(cost, mission, w, params, opts) {
  const full = planOuting(cost, missionPoints(mission, params.stop_min_default), w, params, opts)
  if (!full.ok) return null
  const dist = (p) => p.legs.reduce((s, l) => s + l.distance_m, 0)
  return mission.quests.map((_, k) => {
    const without = { ...mission, quests: mission.quests.filter((__, j) => j !== k) }
    const r = planOuting(cost, missionPoints(without, params.stop_min_default), w, params, opts)
    if (!r.ok) return null
    return {
      min: full.plan.totals.total_min - r.plan.totals.total_min,
      m: dist(full.plan) - dist(r.plan),
      dose: (full.plan.radiation_dose_usv ?? 0) - (r.plan.radiation_dose_usv ?? 0),
      risk: full.plan.risk_min - r.plan.risk_min,
    }
  })
}

// The visiting order of the side quests that gives the shortest walk (physical walking time).
// Exact for up to 7 quests; nearest-neighbour then 2-opt beyond that. Returns the quest indices.
export function bestOrder(cost, mission) {
  const { start, quests = [], dest, back } = mission
  const n = quests.length
  if (n < 2 || !start || !dest) return quests.map((_, k) => k)
  const pts = [start, ...quests, dest]
  const cells = pts.map((p) => snapToFree(cost, p.x, p.y)?.i ?? null)
  const fields = cells.map((c) => (c == null ? null : timeField(cost, c)))
  const t = (a, b) => (fields[a] && cells[b] != null ? fields[a][cells[b]] : Infinity)
  const D = n + 1 // index of dest in pts
  const total = (order) => {
    let s = t(0, order[0] + 1)
    for (let k = 1; k < order.length; k++) s += t(order[k - 1] + 1, order[k] + 1)
    s += t(order[order.length - 1] + 1, D)
    return s + (back ? t(D, 0) : 0)
  }
  let best = quests.map((_, k) => k)
  let bestT = total(best)
  if (n <= 7) {
    const perm = (arr, used, cur) => {
      if (cur.length === n) {
        const v = total(cur)
        if (v < bestT) {
          bestT = v
          best = cur.slice()
        }
        return
      }
      for (let k = 0; k < n; k++) {
        if (used[k]) continue
        used[k] = 1
        cur.push(k)
        perm(arr, used, cur)
        cur.pop()
        used[k] = 0
      }
    }
    perm(quests, new Uint8Array(n), [])
    return best
  }
  // Nearest neighbour from the start, then 2-opt swaps while they help.
  const left = new Set(best)
  const order = []
  let at = 0
  while (left.size) {
    let pick = null
    for (const k of left) if (pick == null || t(at, k + 1) < t(at, pick + 1)) pick = k
    order.push(pick)
    left.delete(pick)
    at = pick + 1
  }
  best = order
  bestT = total(best)
  for (let improved = true; improved; ) {
    improved = false
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 1; j < n; j++) {
        const cand = [...best.slice(0, i), ...best.slice(i, j + 1).reverse(), ...best.slice(j + 1)]
        const v = total(cand)
        if (v + 1e-9 < bestT) {
          best = cand
          bestT = v
          improved = true
        }
      }
    }
  }
  return best
}

// Areas where minerals.png shows a mineral: groups of touching cells of the same mineral, biggest first.
// img: ImageData of minerals.png; legend: layers.json legend [{ label, color }]; grid: { width, height, cellM }.
// Returns [{ id, mineral, color, cells, areaM2, x, y }] where (x, y) is the walkable cell nearest the middle.
export function mineralTargets(img, legend, cost, { minCells = 6, max = 40 } = {}) {
  if (!img || !legend?.length || !cost) return []
  const { width, height, cellM } = cost
  const hex = (h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16))
  const cols = legend.map((e) => hex(e.color))
  const cls = new Int8Array(width * height).fill(-1)
  for (let r = 0; r < height; r++) {
    for (let c = 0; c < width; c++) {
      const pr = Math.min(img.height - 1, Math.floor(((r + 0.5) / height) * img.height))
      const pc = Math.min(img.width - 1, Math.floor(((c + 0.5) / width) * img.width))
      const p = (pr * img.width + pc) * 4
      if (img.data[p + 3] === 0) continue
      let best = -1
      let bd = 60 ** 2
      cols.forEach(([R, G, B], k) => {
        const d = (R - img.data[p]) ** 2 + (G - img.data[p + 1]) ** 2 + (B - img.data[p + 2]) ** 2
        if (d < bd) {
          bd = d
          best = k
        }
      })
      cls[r * width + c] = best
    }
  }
  const seen = new Uint8Array(width * height)
  const out = []
  for (let i = 0; i < cls.length; i++) {
    if (cls[i] < 0 || seen[i]) continue
    const k = cls[i]
    const stack = [i]
    seen[i] = 1
    let n = 0
    let sx = 0
    let sy = 0
    while (stack.length) {
      const j = stack.pop()
      n++
      const r = Math.floor(j / width)
      const c = j % width
      sx += c
      sy += r
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const rr = r + dr
          const cc = c + dc
          if (rr < 0 || cc < 0 || rr >= height || cc >= width) continue
          const q = rr * width + cc
          if (!seen[q] && cls[q] === k) {
            seen[q] = 1
            stack.push(q)
          }
        }
      }
    }
    if (n < minCells) continue
    const mx = (sx / n + 0.5) * cellM
    const my = (height - sy / n - 0.5) * cellM
    const snap = snapToFree(cost, mx, my, 60)
    if (!snap) continue
    const [x, y] = centreOf(snap.i, width, height, cellM)
    out.push({ mineral: legend[k].label, color: legend[k].color, cells: n, areaM2: n * cellM * cellM, x, y, i: snap.i })
  }
  out.sort((a, b) => b.cells - a.cells)
  return out.slice(0, max).map((t, k) => ({ ...t, id: `m${k + 1}` }))
}
