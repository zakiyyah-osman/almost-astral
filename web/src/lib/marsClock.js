// Mars time from Earth time: the Mars24 algorithm (Allison & McEwen 2000, Planetary and Space
// Science 48, 215-235), steps A-1 to C-4 as published at
// https://www.giss.nasa.gov/tools/mars24/help/algorithm.html (checked 14 Nov 2026).
// Pure maths, no React. Angles in degrees, longitude in degrees EAST (0-360) like layers.json.

const DEG = Math.PI / 180
const sin = (d) => Math.sin(d * DEG)
const cos = (d) => Math.cos(d * DEG)
const mod = (x, m) => ((x % m) + m) % m

// TAI-UTC in seconds from each date on (IERS leap second table). No leap second has been added
// since 1 Jan 2017. Dates before 1999 use 32 s, which is out by at most a few seconds: fine here.
const LEAP_SECONDS = [
  [Date.UTC(2017, 0, 1), 37],
  [Date.UTC(2015, 6, 1), 36],
  [Date.UTC(2012, 6, 1), 35],
  [Date.UTC(2009, 0, 1), 34],
  [Date.UTC(2006, 0, 1), 33],
]

// A-4: TT - UTC in seconds = (TAI - UTC) + 32.184 s.
export function ttMinusUtc(millis) {
  const row = LEAP_SECONDS.find(([from]) => millis >= from)
  return (row ? row[1] : 32) + 32.184
}

// The 7 perturbation terms of B-3: amplitude A (deg), period tau (Julian years), phase phi (deg).
const PBS_TERMS = [
  [0.0071, 2.2353, 49.409],
  [0.0057, 2.7543, 168.173],
  [0.0039, 1.1177, 191.837],
  [0.0037, 15.7866, 21.736],
  [0.0021, 2.1354, 15.704],
  [0.0020, 2.4694, 95.528],
  [0.0018, 32.8493, 49.095],
]

// Everything at one instant. millis = Unix time in ms (Date.now()), lonEast = site longitude.
export function marsTime(millis, lonEast = 0) {
  const jdUT = 2440587.5 + millis / 8.64e7 // A-2
  const jdTT = jdUT + ttMinusUtc(millis) / 86400 // A-5
  const dt = jdTT - 2451545.0 // A-6: days since J2000 (TT)

  const M = 19.3871 + 0.52402073 * dt // B-1: mean anomaly
  const alphaFMS = 270.3871 + 0.524038496 * dt // B-2: fictitious mean sun
  const pbs = PBS_TERMS.reduce((s, [A, tau, phi]) => s + A * cos((0.985626 * dt) / tau + phi), 0) // B-3
  const nuM = (10.691 + 3.0e-7 * dt) * sin(M) + 0.623 * sin(2 * M) + 0.05 * sin(3 * M) + 0.005 * sin(4 * M) + 0.0005 * sin(5 * M) + pbs // B-4
  const ls = mod(alphaFMS + nuM, 360) // B-5: areocentric solar longitude

  const eot = 2.861 * sin(2 * ls) - 0.071 * sin(4 * ls) + 0.002 * sin(6 * ls) - nuM // C-1, degrees
  const msd = (jdTT - 2451549.5) / 1.0274912517 + 44796.0 - 0.0009626 // Mars sol date
  const mst = mod(24 * msd, 24) // C-2: Airy mean time, hours
  const lmst = mod(mst + lonEast / 15, 24) // C-3 (east longitude = minus west longitude)
  const ltst = mod(lmst + eot / 15, 24) // C-4

  return { jdUT, jdTT, dt, M: mod(M, 360), alphaFMS: mod(alphaFMS, 360), pbs, nuM, ls, eot, msd, mst, lmst, ltst }
}

// Subsolar point: where the Sun is straight overhead at this instant, from a marsTime() result.
// Latitude = solar declination (Mars24 D-1). Longitude is where local true solar time is 12:00,
// i.e. LTST = MST + lon/15 + EOT/15 = 12, so lon = 180 - 15 * MST - EOT (degrees east, 0-360).
export function subsolarPoint(t) {
  const lat = Math.asin(0.42565 * sin(t.ls)) / DEG + 0.25 * sin(t.ls)
  const lonEast = mod(180 - 15 * t.mst - t.eot, 360)
  return { lat, lonEast }
}

// Season by Ls. Jezero is at 18 N, so northern seasons apply (0 = northern spring equinox).
export function season(ls, lat = 1) {
  const north = ['spring', 'summer', 'autumn', 'winter']
  const south = ['autumn', 'winter', 'spring', 'summer']
  const name = (lat >= 0 ? north : south)[Math.floor(mod(ls, 360) / 90)]
  return `${lat >= 0 ? 'Northern' : 'Southern'} ${name}`
}

// Hours (0-24) as HH:MM:SS.
export function hms(hours) {
  const s = Math.floor(mod(hours, 24) * 3600 + 1e-6)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`
}
