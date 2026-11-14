// Small synthetic cost grids for the tests, in the shape costFromLanding (landingData.js) returns.
// timeRate: minutes per metre; riskRate: risk-minutes per minute; mask: 0 passable, else a blocked code.
import { readFileSync } from 'node:fs'
import { loadLanding, costFromLanding } from './landingData.js'

export const FLAT_RATE = 1 / 45 // 2.7 km/h = 45 m/min on flat ground

export function gridCost({ width, height, cellM = 5, timeRate, riskRate, mask, dem = null, slope = null, hazard = null }) {
  const n = width * height
  const m = mask ?? new Uint8Array(n)
  const t = new Float64Array(n)
  const r = new Float64Array(n)
  for (let i = 0; i < n; i++) {
    t[i] = m[i] ? -1 : timeRate ? timeRate[i] : FLAT_RATE
    r[i] = m[i] ? 0 : riskRate ? riskRate[i] : 0
  }
  const blocked = new Uint8Array(n)
  for (let i = 0; i < n; i++) blocked[i] = m[i] ? 1 : 0
  return {
    width,
    height,
    cellM,
    origin: [0, 0],
    mask: m,
    blocked,
    timeRate: t,
    riskRate: r,
    dem: dem ?? new Float32Array(n),
    slope: slope ?? new Float32Array(n),
    hazard: hazard ?? new Uint8Array(n),
    budget: { ingress_min: 15, stop_min: 25, usable_min: 252 },
    maskCodes: [
      { code: 2, name: 'red', text: 'red hazard cell' },
      { code: 6, name: 'walled_off', text: 'passable, but walled off from the start by blocked cells' },
    ],
    searches: new Map(),
  }
}

// The real export in data/out/landing/, read from disk.
const OUT = new URL('../../../data/out/', import.meta.url)
export const readOut = (p) => readFileSync(new URL(p, OUT))
export const readOutJson = (p) => JSON.parse(readOut(p).toString('utf8'))
export const realLanding = () => loadLanding(async (p) => readOutJson(p), async (p) => readOut(p))
export const realCost = async (terrain = null) => {
  const g = await realLanding()
  return { g, cost: costFromLanding(g, terrain) }
}
