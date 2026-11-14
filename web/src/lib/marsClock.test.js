// Checks marsClock.js against the two worked examples printed on the Mars24 algorithm page
// (https://www.giss.nasa.gov/tools/mars24/help/algorithm.html, fetched 14 Nov 2026).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { hms, marsTime, season, ttMinusUtc } from './marsClock.js'

const near = (got, want, tol, what) => assert.ok(Math.abs(got - want) <= tol, `${what}: got ${got}, want ${want}`)

test('Mars24 example 1: 2000-01-06 00:00:00 UTC at 0 deg longitude', () => {
  const ms = Date.UTC(2000, 0, 6, 0, 0, 0)
  assert.equal(ms, 947116800000)
  assert.equal(ttMinusUtc(ms), 64.184)
  const t = marsTime(ms, 0)
  near(t.jdTT, 2451549.50074, 1e-5, 'JD TT')
  near(t.dt, 4.50074, 1e-5, 'days since J2000')
  near(t.M, 21.74558, 1e-4, 'M')
  near(t.alphaFMS, 272.74566, 1e-4, 'alpha FMS')
  near(t.pbs, 0.00142, 1e-5, 'PBS')
  near(t.nuM, 4.44193, 1e-4, 'nu - M')
  near(t.ls, 277.18758, 1e-4, 'Ls')
  near(t.eot, -5.18774, 1e-4, 'EOT')
  near(t.mst, 23.99425, 1e-4, 'MST')
  near(t.lmst, 23.99425, 1e-4, 'LMST')
  near(t.ltst, 23.6484, 1e-4, 'LTST')
  near(t.msd, 1075103.99425 / 24, 1e-5, 'MSD')
  assert.equal(hms(t.mst), '23:59:39')
})

test('Mars24 example 2: Spirit landing, 2004-01-03 13:46:31 UTC at 184.702 W', () => {
  const ms = Date.UTC(2004, 0, 3, 13, 46, 31)
  assert.equal(ms, 1073137591000)
  const t = marsTime(ms, 360 - 184.702) // 184.702 W = 175.298 E
  near(t.dt, 1463.07471, 1e-5, 'days since J2000')
  near(t.M, 66.06858, 1e-4, 'M')
  near(t.alphaFMS, 317.09457, 1e-4, 'alpha FMS')
  near(t.pbs, 0.01614, 1e-5, 'PBS')
  near(t.nuM, 10.22959, 1e-4, 'nu - M')
  near(t.ls, 327.32416, 1e-4, 'Ls')
  near(t.eot, -12.77553, 1e-4, 'EOT')
  near(t.mst, 13.16537, 1e-4, 'MST')
  near(t.lmst, 0.8519, 1e-4, 'LMST')
  near(t.ltst, 0.00025, 1e-4, 'LTST')
})

test('leap seconds: TT - UTC is 69.184 s from 2017', () => {
  assert.equal(ttMinusUtc(Date.UTC(2026, 10, 14)), 69.184)
  assert.equal(ttMinusUtc(Date.UTC(2016, 11, 31)), 68.184)
})

test('seasons follow Ls, flipped in the south', () => {
  assert.equal(season(10, 18.46), 'Northern spring')
  assert.equal(season(277, 18.46), 'Northern winter')
  assert.equal(season(100, -5), 'Southern winter')
})
