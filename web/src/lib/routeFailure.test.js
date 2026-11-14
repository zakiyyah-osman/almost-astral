import test from 'node:test'
import assert from 'node:assert/strict'
import { routeFailure, unreachableText } from './routeFailure.js'
import { planOuting } from './outing.js'
import { missionPoints } from './mission.js'
import { DEFAULT_PARAMS } from './pathfind.js'
import { gridCost } from './testGrid.js'

const P = { ...DEFAULT_PARAMS }

// 60 x 60 flat cells of 5 m; a closed box of red (mask 2) cells around rows/cols 40-50, with a
// cliff-buffer ring (mask 4) round the outside of it.
function site() {
  const W = 60
  const mask = new Uint8Array(W * W)
  for (let r = 38; r <= 52; r++) for (let c = 38; c <= 52; c++) {
    const edge = r === 38 || r === 52 || c === 38 || c === 52
    const wall = r === 39 || r === 51 || c === 39 || c === 51
    if (edge) mask[r * W + c] = 4
    else if (wall) mask[r * W + c] = 2
  }
  return gridCost({ width: W, height: W, mask, maskCodes: undefined })
}
const cost = site()
cost.maskCodes = [
  { code: 2, name: 'red', text: 'red hazard cell' },
  { code: 4, name: 'buffer', text: 'inside the 5 m buffer around over-limit slopes' },
  { code: 6, name: 'walled_off', text: 'passable, but walled off from the start by blocked cells' },
]
const xy = (r, c) => ({ x: (c + 0.5) * 5, y: (60 - r - 0.5) * 5 })
const plan = (dest, quests = []) => planOuting(cost, missionPoints({ start: { ...xy(5, 5), name: 'Landing' }, quests, dest: { ...xy(...dest), name: 'J0' } }, 25), 1, P, { ingress: true })

test('a destination on a buffer cell fails with its mask reason and a pop-up text', () => {
  const r = plan([38, 45])
  assert.equal(r.ok, false)
  assert.equal(r.reason, 4)
  const f = routeFailure(r)
  assert.equal(f.title, 'No walking route')
  assert.equal(f.messages[0].title, 'Blocked point')
  assert.match(f.messages[0].detail, /^The destination \(J0\) is on a cell the crew may not enter: inside the 5 m buffer/)
})

test('a walled-off destination and a blocked side quest name the point', () => {
  const walled = plan([45, 45])
  assert.equal(walled.reason, 6)
  assert.equal(unreachableText(walled), 'No walking route to the destination (J0): passable, but walled off from the start by blocked cells.')
  const quest = plan([10, 10], [{ ...xy(39, 45), name: 'Red rock' }])
  assert.equal(quest.reason, 2)
  assert.match(routeFailure(quest).messages[0].detail, /^Side quest 1 \(Red rock\) is on a cell/)
})

test('the failure key changes with the failing point, so the pop-up opens once per new failure', () => {
  const a = routeFailure(plan([38, 45]))
  assert.equal(routeFailure(plan([38, 45])).key, a.key)
  assert.notEqual(routeFailure(plan([38, 46])).key, a.key)
  assert.equal(routeFailure(plan([10, 10])), null) // a route that works is not a failure
})
