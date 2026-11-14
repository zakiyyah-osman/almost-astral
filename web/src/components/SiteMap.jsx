import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { clock } from '../hud/sim.js'
import { MARS_RADIUS_M, xyToLatLon, latLonToXY, lon180, siteBounds, fmtLat, fmtLon } from '../lib/geo.js'
import { TREK_LAYERS, TREK_ATTRIBUTION, CRATER } from '../lib/marsTrek.js'

// Two ways to draw the site:
// - Real site (layers.json has site.center_lat / center_lon_east): a Mars map in latitude and
//   longitude (Leaflet EPSG4326, with the Mars radius so the scale bar is right), NASA Mars Trek
//   imagery underneath, and our 2 km square placed on it with geo.js. Start on the whole crater.
// - Fake site (no centre): the flat CRS.Simple grid as before, a point at (x, y) is L.latLng(y, x).
// Everything coming in and going out of this component stays in local site metres (x east, y north),
// so the route finder and the HUD do not change.

const MARS_CRS = L.extend({}, L.CRS.EPSG4326, { R: MARS_RADIUS_M })
const BLANK_TILE = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==' // 1 x 1 see-through
const BOX_MAX_ZOOM = 14 // the "Delta front site" box shows below this zoom

function makeGeo(site) {
  const [w, h] = site.extent_m
  if (site.center_lat == null || site.center_lon_east == null) {
    return {
      real: false,
      toLL: (x, y) => L.latLng(y, x),
      toXY: (ll) => ({ x: ll.lng, y: ll.lat }),
      bounds: L.latLngBounds([0, 0], [h, w]),
    }
  }
  const b = siteBounds(site)
  return {
    real: true,
    toLL: (x, y) => {
      const ll = xyToLatLon(x, y, site)
      return L.latLng(ll.lat, lon180(ll.lon))
    },
    toXY: (ll) => latLonToXY(ll.lat, ll.lng, site),
    bounds: L.latLngBounds([b.south, b.west], [b.north, b.east]),
  }
}

function craterBounds() {
  const r = (CRATER.diameterKm * 1000) / 2 / MARS_RADIUS_M / (Math.PI / 180) // degrees of latitude
  const rl = r / Math.cos((CRATER.lat * Math.PI) / 180)
  return L.latLngBounds([CRATER.lat - r, CRATER.lon - rl], [CRATER.lat + r, CRATER.lon + rl])
}

// A crater-wide image with the site square made see-through, so the detailed site layers take over
// there. Both grids are equirectangular, so latitude and longitude map linearly onto pixels.
// Resolves to a data URL, or null if the image cannot be read.
function withSiteHole(src, bounds, site) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0)
        const w = bounds.getEast() - bounds.getWest()
        const h = bounds.getNorth() - bounds.getSouth()
        const x0 = ((site.getWest() - bounds.getWest()) / w) * canvas.width
        const x1 = ((site.getEast() - bounds.getWest()) / w) * canvas.width
        const y0 = ((bounds.getNorth() - site.getNorth()) / h) * canvas.height
        const y1 = ((bounds.getNorth() - site.getSouth()) / h) * canvas.height
        ctx.clearRect(Math.floor(x0), Math.floor(y0), Math.ceil(x1 - x0) + 1, Math.ceil(y1 - y0) + 1)
        resolve(canvas.toDataURL('image/png'))
      } catch {
        resolve(null)
      }
    }
    img.onerror = () => resolve(null)
    img.src = src
  })
}

// Camera pins for the ground photos (lib/photos.js records). Tapping one opens the photo with its
// sol, camera and credit.
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const cameraIcon = L.divIcon({ className: 'pin-icon', html: '<span class="photo-pin" aria-label="Ground photo"></span>', iconSize: [20, 20], iconAnchor: [10, 10] })

function photoPins(photos) {
  const group = L.layerGroup()
  for (const p of photos) {
    const html =
      `<figure class="photo-pop"><img src="${escapeHtml(p.url)}" alt="Perseverance ${escapeHtml(p.camera)} image, sol ${escapeHtml(p.sol)}" loading="lazy" />` +
      `<figcaption><b>Sol ${escapeHtml(p.sol)}</b> · ${escapeHtml(p.camera)}${p.date_utc ? ` · ${escapeHtml(String(p.date_utc).slice(0, 10))}` : ''}<br />` +
      `Taken where the rover stood, about 2 m up. <span class="credit">Credit: ${escapeHtml(p.credit)}</span><br />` +
      `<small>${escapeHtml(p.image_id)}</small></figcaption></figure>`
    L.marker([p.lat, lon180(p.lon)], { icon: cameraIcon, keyboard: false, title: `Ground photo, sol ${p.sol}` })
      .bindPopup(html, { maxWidth: 340, minWidth: 260, className: 'photo-popup' })
      .addTo(group)
  }
  return group
}

const pinIcon = (label, kind, selected) =>
  L.divIcon({
    className: 'pin-icon',
    html: `<span class="pin ${kind}${selected ? ' selected' : ''}">${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })

// A small Leaflet control holding a button or a line of text.
function control(position, className, html, onClick) {
  const Ctl = L.Control.extend({
    onAdd() {
      const el = L.DomUtil.create(onClick ? 'button' : 'div', className)
      el.innerHTML = html
      if (onClick) {
        el.type = 'button'
        L.DomEvent.on(el, 'click', (e) => {
          L.DomEvent.stop(e)
          onClick()
        })
      }
      L.DomEvent.disableClickPropagation(el)
      return el
    },
  })
  return new Ctl({ position })
}

// Props:
//  route        the active route (GeoJSON), drawn bold
//  refRoute     the team planner's route.geojson, drawn thin for comparison (or null)
//  waypoints    rover and stops; arrivals: { id: minutes } for the "T+hh:mm" labels
//  landing      recommended landing spots [{ x, y, label, title }]
//  ends         custom route ends { start: {x, y}, end: {x, y} } (either may be missing)
//  picking      'start' | 'end' | null: the next map click inside the site sets that point (onPick)
//  onHover      gets { x, y } under the pointer inside the site, or null
//  probe        { x, y }: a point to ring (from the profile chart)
//  astronaut    null, or { x, y, storm, trail } while the HUD simulation runs
//  layoutKey    changes whenever the page layout changes the map's size
export default function SiteMap({ data, extraLayers = [], layerState, route, refRoute, waypoints, arrivals, landing, ends, picking, onPick, onHover, probe, selectedStop, onSelectStop, astronaut, layoutKey }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const mapRef = useRef(null)
  const geoRef = useRef(null)
  const focus = useRef('site') // 'crater' or 'site': what a layout change refits to
  const overlays = useRef({})
  const groups = useRef({})
  const astro = useRef({ marker: null, trail: null })
  const probeDot = useRef(null)
  const cb = useRef({})
  cb.current = { onSelectStop, onPick, onHover, picking }

  // The map, the base imagery and the image layers: rebuilt only when the site itself changes.
  useEffect(() => {
    const geo = makeGeo(data.site)
    geoRef.current = geo
    const site = geo.bounds
    const inside = (ll) => site.contains(ll)
    const toLL = (c) => geo.toLL(c[0], c[1])

    const map = geo.real
      ? L.map(elRef.current, { crs: MARS_CRS, minZoom: 3, maxZoom: 18, zoomSnap: 0.25, wheelPxPerZoomLevel: 90, attributionControl: false, worldCopyJump: false })
      : L.map(elRef.current, { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25, attributionControl: false })
    map.createPane('layers').style.zIndex = 300 // above the base tiles, below the route and markers
    L.control.scale({ imperial: false }).addTo(map)

    const crater = geo.real ? craterBounds() : site
    const flyTo = (target) => {
      focus.current = target
      map.flyToBounds(target === 'site' ? site : crater, { duration: 1.6, padding: target === 'site' ? [12, 12] : [0, 0] })
    }

    if (geo.real) {
      L.control.attribution({ prefix: false }).addAttribution(TREK_ATTRIBUTION).addTo(map)
      TREK_LAYERS.forEach((t, i) =>
        L.tileLayer(t.url, {
          maxZoom: 18,
          noWrap: true,
          errorTileUrl: BLANK_TILE, // a missing tile (404/400) means no coverage: show nothing
          zIndex: i,
          crossOrigin: true,
          ...t.options, // zoom limits, tile size and bounds (no requests outside the mosaic)
        }).addTo(map),
      )

      // The site box: visible when zoomed out; a click flies down to the site.
      const box = L.rectangle(site, { color: '#ffd166', weight: 2, fill: true, fillOpacity: 0.08, className: 'site-box' })
        .bindTooltip('Delta front site', { permanent: true, direction: 'top', className: 'site-box-label' })
        .on('click', () => flyTo('site'))
      const showBox = () => {
        const want = map.getZoom() < BOX_MAX_ZOOM
        if (want && !map.hasLayer(box)) box.addTo(map)
        if (!want && map.hasLayer(box)) box.remove()
      }
      map.on('zoomend', showBox)
      // Zooming by hand also decides what a layout change refits to.
      map.on('zoomend', () => {
        if (!map._flying) focus.current = map.getZoom() >= BOX_MAX_ZOOM - 1 && map.getBounds().intersects(site) ? 'site' : 'crater'
      })

      control('topright', 'map-btn', 'Back to crater', () => flyTo('crater')).addTo(map)
      control('topright', 'map-btn', 'Go to site', () => flyTo('site')).addTo(map)

      // Latitude and longitude under the pointer, anywhere on the map.
      const coords = control('bottomright', 'map-coords', '&nbsp;')
      coords.addTo(map)
      const el = coords.getContainer()
      map.on('mousemove', (e) => (el.textContent = `${fmtLat(e.latlng.lat)}, ${fmtLon((e.latlng.lng + 360) % 360)}`))
      map.on('mouseout', () => (el.innerHTML = '&nbsp;'))

      focus.current = 'crater'
      map.fitBounds(crater, { animate: false })
      showBox()
    } else {
      map.fitBounds(site)
    }

    map.createPane('craterLayers').style.zIndex = 290 // crater-wide layers sit under the site layers
    data.layers.forEach((layer, i) => {
      if (layer.scope === 'photos') {
        if (geo.real) overlays.current[layer.id] = photoPins(data.photos ?? [])
        return
      }
      if (layer.scope === 'crater') {
        if (!geo.real || !layer.bounds) return // needs the lat/lon map
        const b = layer.bounds
        const bounds = L.latLngBounds([b.south, lon180(b.west)], [b.north, lon180(b.east)])
        const overlay = L.imageOverlay(`./${layer.file}`, bounds, { pane: 'craterLayers', zIndex: i })
        overlays.current[layer.id] = overlay
        withSiteHole(`./${layer.file}`, bounds, site).then((url) => url && overlay.setUrl(url))
        return
      }
      overlays.current[layer.id] = L.imageOverlay(`./${layer.file}`, site, { pane: 'layers', zIndex: i })
    })
    groups.current = { routes: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) }
    groups.current.toLL = toLL

    map.on('click', (e) => {
      const { picking: p, onPick: pick } = cb.current
      if (p && pick && inside(e.latlng)) pick(p, geo.toXY(e.latlng))
    })
    let frame = 0
    map.on('mousemove', (e) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => cb.current.onHover?.(inside(e.latlng) ? geo.toXY(e.latlng) : null))
    })
    map.on('mouseout', () => cb.current.onHover?.(null))

    // The map's box changes size when the HUD opens or the window changes: refit it, once, without
    // animation, to the site or the crater, whichever was last chosen.
    let timer = 0
    refit.current = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        map.invalidateSize({ animate: false })
        map.fitBounds(focus.current === 'site' ? site : crater, { animate: false, padding: focus.current === 'site' ? [12, 12] : [0, 0] })
      }, 60)
    }
    refit.current.flyTo = flyTo
    const resize = new ResizeObserver(() => refit.current())
    resize.observe(elRef.current)
    mapRef.current = map
    return () => {
      clearTimeout(timer)
      cancelAnimationFrame(frame)
      refit.current = () => {}
      resize.disconnect()
      map.remove()
      mapRef.current = null
      overlays.current = {}
      groups.current = {}
      astro.current = { marker: null, trail: null }
      probeDot.current = null
    }
  }, [data])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    for (const l of extraLayers) {
      if (!overlays.current[l.id] && l.url) overlays.current[l.id] = L.imageOverlay(l.url, geoRef.current.bounds, { pane: 'layers', zIndex: data.layers.length + 1 })
    }
    for (const [id, state] of Object.entries(layerState)) {
      const overlay = overlays.current[id]
      if (!overlay) continue
      overlay.setOpacity?.(state.opacity) // photo pins are a layer group: no opacity
      if (state.on && !map.hasLayer(overlay)) overlay.addTo(map)
      if (!state.on && map.hasLayer(overlay)) overlay.remove()
    }
  }, [layerState, data, extraLayers])

  useEffect(() => {
    refit.current()
  }, [layoutKey])

  // Routes: the team planner's route thin underneath, the active route bold on top.
  useEffect(() => {
    const g = groups.current.routes
    if (!g) return
    const toLL = groups.current.toLL
    g.clearLayers()
    if (refRoute) {
      L.geoJSON(refRoute, { coordsToLatLng: toLL, interactive: false, style: { color: '#c9b8ad', weight: 2, opacity: 0.8, dashArray: '2 6' } }).addTo(g)
    }
    if (route) {
      L.geoJSON(route, { coordsToLatLng: toLL, interactive: false, style: { color: '#1a0e09', weight: 7, opacity: 0.7 } }).addTo(g)
      L.geoJSON(route, { coordsToLatLng: toLL, interactive: false, style: { color: '#ffffff', weight: 3, opacity: 0.95, dashArray: '6 6' } }).addTo(g)
    }
  }, [route, refRoute, data])

  // Pins: rover and stops, landing suggestions, custom start and end.
  useEffect(() => {
    const g = groups.current.pins
    if (!g) return
    const toLL = groups.current.toLL
    g.clearLayers()
    let n = 0
    for (const f of waypoints?.features ?? []) {
      const kind = f.properties.kind
      if (kind !== 'rover' && kind !== 'stop') continue
      const rover = kind === 'rover'
      const t = arrivals?.[f.properties.id]
      const label = rover ? `${f.properties.name} · start` : `${f.properties.name}${t != null ? ` · T+${clock(t)}` : ''}`
      L.marker(toLL(f.geometry.coordinates), { icon: pinIcon(rover ? 'R' : ++n, rover ? 'rover' : 'stop', f.properties.id === selectedStop), keyboard: false })
        .bindTooltip(label, { permanent: true, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', () => cb.current.onSelectStop?.(f.properties.id))
        .addTo(g)
    }
    for (const s of landing ?? []) {
      L.marker(toLL([s.x, s.y]), { icon: pinIcon(s.label, 'landing'), keyboard: false })
        .bindTooltip(s.title, { direction: 'top', offset: [0, -14], className: 'stop-label' })
        .on('click', () => cb.current.onSelectStop?.(s.id))
        .addTo(g)
    }
    for (const [key, label] of [['start', 'A'], ['end', 'B']]) {
      const p = ends?.[key]
      if (p) L.marker(toLL([p.x, p.y]), { icon: pinIcon(label, `end-${key}`), keyboard: false, interactive: false }).addTo(g)
    }
  }, [waypoints, arrivals, landing, ends, selectedStop, data])

  // Crosshair while picking a point.
  useEffect(() => {
    elRef.current?.classList.toggle('picking', !!picking)
  }, [picking])

  // A ring where the profile chart is pointing.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!probe) {
      probeDot.current?.remove()
      probeDot.current = null
      return
    }
    const ll = geoRef.current.toLL(probe.x, probe.y)
    if (!probeDot.current) probeDot.current = L.circleMarker(ll, { radius: 9, color: '#ffffff', weight: 3, fillColor: '#e0714f', fillOpacity: 0.9, interactive: false }).addTo(map)
    else probeDot.current.setLatLng(ll)
  }, [probe, data])

  // The moving astronaut and the trail behind them. When the walk starts, go to the site.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const a = astro.current
    if (!astronaut) {
      a.marker?.remove()
      a.trail?.remove()
      a.marker = a.trail = null
      return
    }
    const toLL = geoRef.current.toLL
    const colour = astronaut.storm ? '#ff6b57' : '#5eead4'
    const latlng = toLL(astronaut.x, astronaut.y)
    const icon = L.divIcon({ className: 'pin-icon', html: `<span class="astro${astronaut.storm ? ' storm' : ''}"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] })
    if (!a.marker) {
      if (geoRef.current.real && focus.current !== 'site') refit.current.flyTo?.('site')
      a.trail = L.polyline([], { color: colour, weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(map)
      a.marker = L.marker(latlng, { icon, zIndexOffset: 1000, interactive: false, keyboard: false }).addTo(map)
    }
    a.marker.setLatLng(latlng).setIcon(icon)
    a.trail.setStyle({ color: colour }).setLatLngs(astronaut.trail.map((p) => toLL(p[0], p[1])))
  }, [astronaut, data])

  return <div ref={elRef} className="map" />
}
