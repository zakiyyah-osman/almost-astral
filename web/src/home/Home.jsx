// The landing page: a Mars globe with Jezero marked, between two panels. Left: what this is, the live
// clock at Jezero and a day of real weather. Right: the planned walk, or, once Jezero is clicked, a card
// of site stats. Every number names where it comes from (the Real / Calc / Estimate tags; hover for the source).
// main.jsx shows the map (App) at #map.
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import Tag from '../components/Tag.jsx'
import { loadData } from '../lib/loadData.js'
import { parseTable, cardinal } from '../hud/sim.js'
import { distanceBearing, fmtLat, fmtLon, PLACES } from '../lib/geo.js'
import { hms, marsTime, season } from '../lib/marsClock.js'
import { distanceM } from '../lib/photos.js'
import Starfield from './Starfield.jsx'
import './home.css'

// three.js is big: load the globe as its own chunk so the map (#map) never waits for it.
const Globe = lazy(() => import('./Globe.jsx'))

const CLOCK_NOTE = 'Calculated in the browser with the Mars24 algorithm (Allison & McEwen 2000, NASA GISS), from your clock and the site longitude.'
const STORM_TYPES = {
  CME: 'Coronal mass ejection',
  FLR: 'Solar flare',
  SEP: 'Solar energetic particles',
  GST: 'Geomagnetic storm',
  IPS: 'Interplanetary shock',
  RBE: 'Radiation belt enhancement',
  HSS: 'High-speed solar wind stream',
  MPC: 'Magnetopause crossing',
}

const text = (path) => fetch(`./${path}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error(path))))

// space_weather.csv has text cells (and no quoted commas), so a plain split is enough here.
function lastStorm(csv) {
  const lines = String(csv ?? '').trim().split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) return null
  const head = lines[0].split(',').map((h) => h.trim())
  const rows = lines.slice(1).map((l) => {
    const cells = l.split(',')
    return Object.fromEntries(head.map((h, i) => [h, (cells[i] ?? '').trim()]))
  })
  return rows.reduce((a, b) => (Date.parse(b.start_utc) > Date.parse(a.start_utc) ? b : a))
}

// Earth year of a Perseverance sol: landing 18 Feb 2021 20:55 UTC (NASA/JPL), one sol = 88,775.244 s.
const solYear = (sol) => new Date(Date.UTC(2021, 1, 18, 20, 55) + sol * 88775244).getUTCFullYear()

const fmtDate = (iso) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function Tile({ label, tag, wide, children }) {
  return (
    <section className={`tile${wide ? ' wide' : ''}`}>
      <h3 className="tile-label">{label} {tag}</h3>
      {children}
    </section>
  )
}

// 24 hours of sol 420 air temperature as a small line, with a dot at the current local hour.
function WeatherDay({ weather, hour }) {
  const rows = (weather ?? []).filter((r) => Number.isFinite(r.temp_c) && Number.isFinite(r.local_hour)).sort((a, b) => a.local_hour - b.local_hour)
  if (rows.length < 2) return null
  const W = 260
  const H = 70
  const temps = rows.map((r) => r.temp_c)
  const lo = Math.min(...temps)
  const hi = Math.max(...temps)
  const x = (h) => 4 + (h / 23) * (W - 8)
  const y = (t) => 8 + (1 - (t - lo) / (hi - lo || 1)) * (H - 16)
  const line = rows.map((r, i) => `${i ? 'L' : 'M'}${x(r.local_hour).toFixed(1)},${y(r.temp_c).toFixed(1)}`).join(' ')
  const area = `${line} L${x(rows.at(-1).local_hour).toFixed(1)},${H} L${x(rows[0].local_hour).toFixed(1)},${H} Z`
  const nowRow = rows.find((r) => r.local_hour === hour)
  const sol = rows[0].sol
  return (
    <figure className="wx-day">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Air temperature through sol ${sol}: ${lo.toFixed(0)} to ${hi.toFixed(0)} °C${nowRow ? `; ${nowRow.temp_c.toFixed(0)} °C at ${hour}:00` : ''}`}>
        <defs>
          <linearGradient id="wx-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--accent)" stopOpacity="0.35" />
            <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#wx-fill)" />
        <path d={line} fill="none" stroke="var(--accent-strong)" strokeWidth="1.8" strokeLinejoin="round" />
        {nowRow && (
          <>
            <line x1={x(hour)} x2={x(hour)} y1="0" y2={H} className="wx-now-line" />
            <circle cx={x(hour)} cy={y(nowRow.temp_c)} r="3.6" className="wx-now-dot" />
          </>
        )}
      </svg>
      <figcaption className="wx-axis mono">
        <span>00:00</span>
        <span>{hi.toFixed(0)}° / {lo.toFixed(0)}°C</span>
        <span>23:00</span>
      </figcaption>
    </figure>
  )
}

// The left panel: what this is, Jezero's clock right now, a day of real weather, the way in.
function IntroPanel({ data, now }) {
  const site = data?.site
  const t = site ? marsTime(now, site.center_lon_east) : null
  const hour = t ? Math.floor(t.ltst) : null
  const wxSol = data?.weather?.[0]?.sol
  return (
    <aside className="panel panel-left" aria-label="About this site">
      <div className="hero">
        <p className="eyebrow">Interplanetary Survival Guide · Mars</p>
        <h1>Walk Jezero crater, safely</h1>
        <p className="lede">A 2 km square on the delta front where Perseverance works, mapped from NASA orbiter data: where it is safe to walk, what is worth the trip, and when to turn back.</p>
      </div>

      {t && (
        <section className="glass now-card" aria-label="Right now at Jezero">
          <div className="now-head">
            <p className="eyebrow"><span className="live-dot" aria-hidden="true" /> Now at Jezero</p>
            <Tag kind="calc" title={CLOCK_NOTE} />
          </div>
          <p className="now-time mono">{hms(t.lmst)}<span className="unit">LMST</span></p>
          <div className="now-row">
            <span>{season(t.ls, site.center_lat)}</span>
            <span className="mono">Ls {t.ls.toFixed(1)}°</span>
            <span className="mono">MSD {Math.floor(t.msd)}</span>
          </div>
        </section>
      )}

      {data?.weather && (
        <section className="glass" aria-label={`A day of weather, sol ${wxSol}`}>
          <div className="now-head">
            <p className="eyebrow">A day at Jezero · sol {wxSol}</p>
            <Tag kind="real" title={`Perseverance MEDA (Mars 2020), sol ${wxSol} (${solYear(wxSol)}): hourly means of air temperature, from data/out/weather.csv. The dot marks today's local hour.`} />
          </div>
          <WeatherDay weather={data.weather} hour={hour} />
        </section>
      )}

      <a className="btn-primary" href="#map">Open the Jezero map <span aria-hidden="true">→</span></a>
    </aside>
  )
}

// The right panel before Jezero is clicked: real Perseverance photos taken in or near the site,
// nearest the site centre first, as a slideshow.
const NEAR_SITE_M = 1500
function GroundPhotos({ photos, site, onOpen, disabled }) {
  const centre = site ? { lat: site.center_lat, lon: site.center_lon_east } : null
  const list = centre
    ? (photos ?? []).filter((p) => p.url).map((p) => ({ ...p, away: distanceM(centre, p) })).sort((a, b) => a.away - b.away)
    : []
  const near = list.filter((p) => p.away <= NEAR_SITE_M)
  const shown = near.length ? near : list.slice(0, 8)
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const n = shown.length
  const k = n ? i % n : 0

  // Next photo every 7 s, unless the pointer is over it or motion is reduced.
  useEffect(() => {
    if (n < 2 || paused || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined
    const id = setInterval(() => setI((v) => v + 1), 7000)
    return () => clearInterval(id)
  }, [n, paused])
  // Load the next photo early so the change is instant.
  const nextUrl = n > 1 ? shown[(k + 1) % n].url : null
  useEffect(() => {
    if (nextUrl) new Image().src = nextUrl
  }, [nextUrl])

  const p = shown[k]
  return (
    <section className="glass ground" aria-label="Perseverance photos from the site" onPointerEnter={() => setPaused(true)} onPointerLeave={() => setPaused(false)}>
      <div className="now-head">
        <p className="eyebrow">Seen from the ground</p>
        <Tag kind="real" title="NASA Mars 2020 raw images (Navcam and Mastcam-Z), placed where the rover stood using NASA/JPL's published traverse waypoints. From data/out/photos.geojson." />
      </div>
      {p ? (
        <>
          <figure className="photo">
            <img key={p.url} src={p.url} alt={`Jezero crater seen by Perseverance's ${p.camera} on sol ${p.sol}`} loading="lazy" />
            {n > 1 && (
              <>
                <button type="button" className="photo-nav prev" onClick={() => setI(k - 1 + n)} aria-label="Previous photo">‹</button>
                <button type="button" className="photo-nav next" onClick={() => setI(k + 1)} aria-label="Next photo">›</button>
                <span className="photo-count mono">{k + 1} / {n}</span>
              </>
            )}
          </figure>
          <div className="photo-meta">
            <p className="mid">{p.camera}</p>
            <p className="small mono">Sol {p.sol} · {fmtDate(p.date_utc + 'Z')}</p>
            <p className="small">{p.away < 100 ? 'At the site centre' : `${(p.away / 1000).toFixed(1)} km from the site centre`} · {p.credit}</p>
          </div>
        </>
      ) : (
        <p className="small">The ground photos have not loaded.</p>
      )}
      <button type="button" className="btn-ghost" onClick={onOpen} disabled={disabled} aria-controls="site-card">
        <span className="pin-dot" aria-hidden="true" /> Show Jezero site details
      </button>
      <p className="hint">or click the glowing marker on the globe</p>
    </section>
  )
}

function SiteCard({ data, now, onClose }) {
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  // Focus the card once when it opens; Escape closes it.
  useEffect(() => {
    ref.current?.focus({ preventScroll: true })
    const onKey = (e) => e.key === 'Escape' && closeRef.current()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const { site, notes, weather, radiation, storm } = data
  const t = marsTime(now, site.center_lon_east)

  // MEDA rows are hourly means by local TRUE solar time (LTST), so look them up by LTST.
  const hour = Math.floor(t.ltst)
  const wxRow = weather?.find((r) => r.local_hour === hour)
  const wxSol = weather?.[0]?.sol
  const wxNote = `Perseverance MEDA (Mars 2020), measured on sol ${wxSol} (${solYear(wxSol)}) at ${String(hour).padStart(2, '0')}:00 local true solar time, the same hour as now at Jezero. Hourly means from data/out/weather.csv.`

  const radRow = radiation?.find((r) => r.local_hour === hour) ?? radiation?.[0]
  const radDay = radiation?.filter((r) => r.sol === radRow?.sol).reduce((s, r) => s + r.dose_rate_usv_h, 0)
  const radNote = notes['radiation.csv'] ?? 'Curiosity RAD average at Gale, applied at Jezero.'

  const here = { lat: site.center_lat, lon: site.center_lon_east }
  const toLanding = distanceBearing(here, PLACES.landing)

  return (
    <div className="glass site-card" id="site-card" role="dialog" aria-labelledby="site-card-title" tabIndex={-1} ref={ref}>
      <header className="site-card-head">
        <div>
          <p className="eyebrow">Our site</p>
          <h2 id="site-card-title">Jezero crater</h2>
          <p className="small">{site.name.replace(/^Jezero crater,\s*/i, '')}</p>
        </div>
        <button type="button" className="card-close" onClick={onClose} aria-label="Close the Jezero card">×</button>
      </header>

      <div className="tiles">
        <Tile label="Air" tag={<Tag kind="real" title={wxNote} />}>
          <p className="big mono">{wxRow ? wxRow.temp_c.toFixed(0) : '–'}<span className="unit">°C</span></p>
          <p className="small">sol {wxSol} · {String(hour).padStart(2, '0')}:00</p>
        </Tile>
        <Tile label="Pressure" tag={<Tag kind="real" title={wxNote} />}>
          <p className="big mono">{wxRow ? Math.round(wxRow.pressure_pa) : '–'}<span className="unit">Pa</span></p>
          <p className="small">about 0.7 % of Earth&apos;s</p>
        </Tile>
        <Tile label="Radiation" tag={<Tag kind="estimate" title={radNote} />}>
          <p className="big mono">{radRow ? radRow.dose_rate_usv_h.toFixed(1) : '–'}<span className="unit">µSv/h</span></p>
          <p className="small">{radDay ? `${Math.round(radDay)} µSv a day` : 'not loaded'}</p>
        </Tile>
        <Tile label="To landing site" tag={<Tag kind="real" title={`${PLACES.landing.name}: ${fmtLat(PLACES.landing.lat)} ${fmtLon(PLACES.landing.lon)}. ${PLACES.landing.source}.`} />}>
          <p className="big mono">{(toLanding.distanceM / 1000).toFixed(1)}<span className="unit">km</span></p>
          <p className="small">{cardinal(toLanding.bearingDeg)} to Perseverance&apos;s landing</p>
        </Tile>
        <Tile wide label="Latest solar storm" tag={<Tag kind="real" title={`${notes['space_weather.csv'] ?? 'NASA DONKI'} Most recent event in our data, which runs to 31 Dec 2025.`} />}>
          {storm ? (
            <div className="storm">
              <div>
                <p className="mid">{STORM_TYPES[storm.type] ?? storm.type}</p>
                <p className="small mono">{fmtDate(storm.start_utc)}{storm.detail ? ` · ${storm.detail}` : ''}</p>
              </div>
              <span className={`chip ${storm.mars_impact === 'True' ? 'bad' : 'ok'}`}>{storm.mars_impact === 'True' ? 'Hits Mars' : 'Misses Mars'}</span>
            </div>
          ) : (
            <p className="small">space_weather.csv not loaded.</p>
          )}
        </Tile>
        <Tile wide label="Site centre" tag={<Tag kind="assumption" title="Site centre chosen by the team on the USGS HiRISE DTM mosaic of Jezero (data/site.json); not a published coordinate." />}>
          <p className="mid mono">{fmtLat(site.center_lat)} · {fmtLon(site.center_lon_east)}</p>
        </Tile>
      </div>

      <footer className="site-card-foot">
        <a className="btn-primary" href="#map">Open the Jezero map <span aria-hidden="true">→</span></a>
        <p className="hint">Hover a label to see where a number comes from.</p>
      </footer>
    </div>
  )
}

export default function Home() {
  const now = useNow(1000)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(false)
  const opener = useRef(null)

  useEffect(() => {
    let live = true
    loadData()
      .then(async (index) => {
        const t = index.tables ?? {}
        const [wx, rad, sw] = await Promise.all([
          t.weather ? text(t.weather).then(parseTable).catch(() => null) : null,
          t.radiation ? text(t.radiation).then(parseTable).catch(() => null) : null,
          t.space_weather ? text(t.space_weather).then(lastStorm).catch(() => null) : null,
        ])
        if (live) setData({ site: index.site, notes: index.sources_notes ?? {}, photos: index.photos, weather: wx, radiation: rad, storm: sw })
      })
      .catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [])

  const show = () => {
    opener.current = document.activeElement
    setOpen(true)
  }
  const hide = () => {
    setOpen(false)
    opener.current?.focus?.({ preventScroll: true })
  }

  const utc = new Date(now).toISOString()
  const site = data?.site

  return (
    <div className="home">
      <Starfield />
      <header className="home-bar">
        <div className="home-brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <strong>Almost Astral</strong>
            <span className="small">NASA Space Apps 2026 · Martian Map</span>
          </div>
        </div>
        <div className="utc mono" aria-label={`UTC time ${utc.slice(11, 19)}`}>
          <span className="eyebrow">UTC</span>
          <span className="utc-time">{utc.slice(11, 19)}</span>
          <span className="utc-date">{utc.slice(0, 10)}</span>
        </div>
      </header>

      <main className="home-main">
        <IntroPanel data={data} now={now} />

        <div className="globe-area">
          {site && (
            <Suspense fallback={<div className="globe"><div className="globe-fallback" aria-hidden="true" /></div>}>
              <Globe lat={site.center_lat} lon={site.center_lon_east} label="Jezero crater" open={open} onSelect={show} />
            </Suspense>
          )}
          {error && <p className="small">Could not load the site data ({error}).</p>}
        </div>

        <div className="panel panel-right">
          {open && data ? <SiteCard data={data} now={now} onClose={hide} /> : <GroundPhotos photos={data?.photos} site={site} onOpen={show} disabled={!site} />}
        </div>
      </main>
    </div>
  )
}
