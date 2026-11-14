import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { clock } from '../hud/sim.js'
import { graticule } from '../lib/graticule.js'
import { MARS_RADIUS_M, xyToLatLon, latLonToXY, lon180, siteBounds } from '../lib/geo.js'
import { TREK_LAYERS, TREK_ATTRIBUTION, CRATER } from '../lib/marsTrek.js'

// Two ways to draw the site:
// - Real site (layers.json has site.center_lat / center_lon_east): a Mars map in latitude and
//   longitude (Leaflet EPSG4326, with the Mars radius so the scale bar is right), NASA Mars Trek
//   imagery underneath, the crater-wide layers and photo pins, and our 2 km square placed on it with
//   geo.js. It opens on the whole crater; the "Delta front site" box flies down to the site.
// - Fake site (no centre): the flat CRS.Simple grid, where a point at (x, y) is L.latLng(y, x).
// Everything coming in and going out of this component stays in local site metres (x east, y north),
// so the route finder, the mission planner and the HUD do not change.

const MARS_CRS = L.extend({}, L.CRS.EPSG4326, { R: MARS_RADIUS_M })
const BLANK_TILE = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==' // 1 x 1 see-through
const BOX_MAX_ZOOM = 14 // the "Delta front site" box shows below this zoom

function makeGeo(site) {
  const [w, h] = site.extent_m
  if (site.center_lat == null || site.center_lon_east == null) {
    return { real: false, toLL: (x, y) => L.latLng(y, x), toXY: (ll) => ({ x: ll.lng, y: ll.lat }), bounds: L.latLngBounds([0, 0], [h, w]) }
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

// A small Leaflet control holding a button.
function button(position, label, onClick) {
  const Ctl = L.Control.extend({
    onAdd() {
      const el = L.DomUtil.create('button', 'map-btn')
      el.type = 'button'
      el.textContent = label
      L.DomEvent.on(el, 'click', (e) => {
        L.DomEvent.stop(e)
        onClick()
      })
      L.DomEvent.disableClickPropagation(el)
      return el
    },
  })
  return new Ctl({ position })
}

const pinIcon = (label, kind, selected) =>
  L.divIcon({
    className: 'pin-icon',
    html: `<span class="pin ${kind}${selected ? ' selected' : ''}">${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })

// Props (all positions in local site metres):
//  route        the active route (GeoJSON), drawn bold
//  refRoute     the team planner's route.geojson, drawn thin for comparison (or null)
//  waypoints    rover and stops; arrivals: { id: minutes } for the "T+hh:mm" labels
//  landing      recommended landing spots [{ x, y, label, title }]
//  missionPins  the custom mission's own points [{ x, y, label, kind, title }] (start, side quests, destination)
//  targets      mineral areas to pick as side quests [{ id, x, y, color, mineral, areaM2 }]
//  picking      'start' | 'quest' | 'dest' | null: the next map click (or pin click) sets that point (onPick)
//  onInspect    gets { x, y } when the map is clicked and nothing is being picked
//  inspect      { x, y }: the point being inspected, marked with a cross
//  gridOn       draw latitude and longitude lines for the part of the map on screen
//  onView       gets { centre: { x, y } } whenever the map stops moving
//  sizeKey      changes whenever the map's box changes size without a new layout (sidebar dragged)
//  onHover      gets { x, y } under the pointer (anywhere on the map), or null
//  probe        { x, y }: a point to ring (from the profile chart)
//  astronaut    null, or { x, y, storm, trail } while the HUD simulation runs
//  layoutKey    changes whenever the page layout changes the map's size
export default function SiteMap({ data, extraLayers = [], layerState, route, refRoute, waypoints, arrivals, landing, missionPins, targets, picking, onPick, onInspect, inspect, gridOn, onView, onHover, probe, selectedStop, onSelectStop, astronaut, layoutKey, sizeKey }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const flyTo = useRef(() => {})
  const resizeOnly = useRef(() => {})
  const mapRef = useRef(null)
  const geoRef = useRef(makeGeo(data.site))
  const focus = useRef('site') // 'crater' or 'site': what a layout change refits to
  const overlays = useRef({})
  const groups = useRef({})
  const astro = useRef({ marker: null, trail: null })
  const probeDot = useRef(null)
  const inspectMark = useRef(null)
  const drawGrid = useRef(() => {})
  const cb = useRef({})
  cb.current = { onSelectStop, onPick, onHover, onInspect, onView, picking }
  const toLL = (c) => geoRef.current.toLL(c[0], c[1])
  // A pin click picks that pin's place while picking, and selects it otherwise.
  const pinClick = (x, y, name, id) => () => {
    const { picking: p, onPick: pick, onSelectStop: sel } = cb.current
    if (p && pick) pick(p, { x, y, name })
    else if (id) sel?.(id)
  }

  // The map, the base imagery and the image layers: rebuilt only when the site itself changes.
  useEffect(() => {
    const geo = makeGeo(data.site)
    geoRef.current = geo
    const site = geo.bounds
    const crater = geo.real ? craterBounds() : site
    const map = geo.real
      ? L.map(elRef.current, { crs: MARS_CRS, minZoom: 3, maxZoom: 18, zoomSnap: 0.25, wheelPxPerZoomLevel: 90, attributionControl: false })
      : L.map(elRef.current, { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25, attributionControl: false })
    map.createPane('craterLayers').style.zIndex = 290 // crater-wide layers sit under the site layers
    map.createPane('layers').style.zIndex = 300 // below the route and markers
    map.createPane('grid').style.zIndex = 350
    map.getPane('grid').style.pointerEvents = 'none'
    L.control.scale({ imperial: false }).addTo(map)

    const fit = (target, animate) => {
      focus.current = target
      const opts = { padding: target === 'site' ? [12, 12] : [0, 0] }
      if (animate) map.flyToBounds(target === 'site' ? site : crater, { ...opts, duration: 1.6 })
      else map.fitBounds(target === 'site' ? site : crater, { ...opts, animate: false })
    }
    flyTo.current = (target) => fit(target, true)

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
        .on('click', () => flyTo.current('site'))
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
      button('topright', 'Back to crater', () => flyTo.current('crater')).addTo(map)
      button('topright', 'Go to site', () => flyTo.current('site')).addTo(map)
      fit('crater', false)
      showBox()
    } else {
      fit('site', false)
    }

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
    groups.current = { grid: L.layerGroup().addTo(map), routes: L.layerGroup().addTo(map), targets: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) }

    // Clicks pick or inspect points of the site; outside the site square there is no terrain data.
    map.on('click', (e) => {
      if (geo.real && !site.contains(e.latlng)) return
      const { picking: p, onPick: pick, onInspect: insp } = cb.current
      const pt = geo.toXY(e.latlng)
      if (p && pick) pick(p, pt)
      else insp?.(pt)
    })
    map.on('moveend resize', () => {
      cb.current.onView?.({ centre: geo.toXY(map.getCenter()) })
      drawGrid.current()
    })
    let frame = 0
    map.on('mousemove', (e) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => cb.current.onHover?.(geo.toXY(e.latlng)))
    })
    map.on('mouseout', () => cb.current.onHover?.(null))

    // A new layout (HUD opened, visor, big text): refit the site or the crater, whichever was last
    // chosen, once, without animation.
    let timer = 0
    refit.current = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        map.invalidateSize({ animate: false })
        fit(focus.current, false)
        drawGrid.current()
      }, 60)
    }
    // The box only changed size (window resized, sidebar dragged): keep the user's zoom and the centre.
    let sizeFrame = 0
    resizeOnly.current = () => {
      cancelAnimationFrame(sizeFrame)
      sizeFrame = requestAnimationFrame(() => map.invalidateSize({ animate: false }))
    }
    let first = true
    const resize = new ResizeObserver(() => {
      if (first) {
        first = false
        return refit.current()
      }
      resizeOnly.current()
    })
    resize.observe(elRef.current)
    mapRef.current = map
    return () => {
      clearTimeout(timer)
      cancelAnimationFrame(frame)
      cancelAnimationFrame(sizeFrame)
      resizeOnly.current = () => {}
      drawGrid.current = () => {}
      flyTo.current = () => {}
      inspectMark.current = null
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

  useEffect(() => {
    resizeOnly.current()
  }, [sizeKey])

  // Latitude and longitude lines, redrawn whenever the map stops moving. graticule() works in site
  // metres, so the view is converted to metres and each line back to map coordinates.
  useEffect(() => {
    const map = mapRef.current
    const g = groups.current.grid
    if (!map || !g) return
    const site = data.site
    drawGrid.current = () => {
      g.clearLayers()
      if (!gridOn || site.center_lat == null) return
      const geo = geoRef.current
      const b = map.getBounds()
      const sw = geo.toXY(b.getSouthWest())
      const ne = geo.toXY(b.getNorthEast())
      const view = { x0: sw.x, x1: ne.x, y0: sw.y, y1: ne.y }
      const { lats, lons, decimals } = graticule(view, site)
      const style = { pane: 'grid', color: '#f3e9e1', weight: 1, opacity: 0.22, interactive: false }
      const at = (px, py) => geo.toXY(map.containerPointToLatLng([px, py]))
      for (const l of lats) {
        L.polyline([geo.toLL(view.x0, l.y), geo.toLL(view.x1, l.y)], style).addTo(g)
        L.marker(geo.toLL(at(4, 0).x, l.y), { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lat', html: `${l.v.toFixed(decimals)}°N`, iconSize: null }) }).addTo(g)
      }
      for (const l of lons) {
        L.polyline([geo.toLL(l.x, view.y0), geo.toLL(l.x, view.y1)], style).addTo(g)
        L.marker(geo.toLL(l.x, at(0, 4).y), { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lon', html: `${l.v.toFixed(decimals)}°E`, iconSize: null }) }).addTo(g)
      }
    }
    drawGrid.current()
  }, [gridOn, data])

  // Routes: the team planner's route thin underneath, the active route bold on top.
  useEffect(() => {
    const g = groups.current.routes
    if (!g) return
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
    g.clearLayers()
    let n = 0
    for (const f of waypoints?.features ?? []) {
      const kind = f.properties.kind
      if (kind !== 'rover' && kind !== 'stop') continue
      const rover = kind === 'rover'
      const t = arrivals?.[f.properties.id]
      const label = rover ? `${f.properties.name} · start` : `${f.properties.name}${t != null ? ` · T+${clock(t)}` : ''}`
      const [x, y] = f.geometry.coordinates
      L.marker(toLL(f.geometry.coordinates), { icon: pinIcon(rover ? 'R' : ++n, rover ? 'rover' : 'stop', f.properties.id === selectedStop), keyboard: false })
        .bindTooltip(label, { permanent: !missionPins?.length, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', pinClick(x, y, f.properties.name, f.properties.id))
        .addTo(g)
    }
    for (const s of landing ?? []) {
      L.marker(toLL([s.x, s.y]), { icon: pinIcon(s.label, 'landing', s.id === selectedStop), keyboard: false })
        .bindTooltip(s.title, { direction: 'top', offset: [0, -14], className: 'stop-label' })
        .on('click', pinClick(s.x, s.y, `${s.label} landing spot`, s.id))
        .addTo(g)
    }
    for (const p of missionPins ?? []) {
      L.marker(toLL([p.x, p.y]), { icon: pinIcon(p.label, p.kind), keyboard: false, zIndexOffset: 500 })
        .bindTooltip(p.title, { permanent: true, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', pinClick(p.x, p.y, p.name))
        .addTo(g)
    }
  }, [waypoints, arrivals, landing, missionPins, selectedStop, data])

  // Mineral areas that can be picked as side quests: small diamonds in the mineral's colour.
  useEffect(() => {
    const g = groups.current.targets
    if (!g) return
    g.clearLayers()
    for (const t of targets ?? []) {
      const icon = L.divIcon({ className: 'pin-icon', html: `<span class="target" style="--c:${t.color}"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] })
      L.marker(toLL([t.x, t.y]), { icon, keyboard: false })
        .bindTooltip(`${t.mineral} · ${Math.round(t.areaM2).toLocaleString()} m²${t.detourMin != null ? ` · about ${Math.round(t.detourMin)} min off the route` : ''}`, { direction: 'top', offset: [0, -8], className: 'stop-label' })
        .on('click', pinClick(t.x, t.y, `${t.mineral} area`))
        .addTo(g)
    }
  }, [targets, data])

  // The point being inspected.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!inspect) {
      inspectMark.current?.remove()
      inspectMark.current = null
      return
    }
    const ll = toLL([inspect.x, inspect.y])
    if (!inspectMark.current) {
      const icon = L.divIcon({ className: 'pin-icon', html: '<span class="inspect-mark"></span>', iconSize: [26, 26], iconAnchor: [13, 13] })
      inspectMark.current = L.marker(ll, { icon, interactive: false, keyboard: false }).addTo(map)
    } else inspectMark.current.setLatLng(ll)
  }, [inspect, data])

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
    const ll = toLL([probe.x, probe.y])
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
    const colour = astronaut.storm ? '#ff6b57' : '#5eead4'
    const latlng = toLL([astronaut.x, astronaut.y])
    const icon = L.divIcon({ className: 'pin-icon', html: `<span class="astro${astronaut.storm ? ' storm' : ''}"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] })
    if (!a.marker) {
      if (geoRef.current.real && focus.current !== 'site') flyTo.current('site')
      a.trail = L.polyline([], { color: colour, weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(map)
      a.marker = L.marker(latlng, { icon, zIndexOffset: 1000, interactive: false, keyboard: false }).addTo(map)
    }
    a.marker.setLatLng(latlng).setIcon(icon)
    a.trail.setStyle({ color: colour }).setLatLngs(astronaut.trail.map((p) => toLL(p)))
  }, [astronaut, data])

  return <div ref={elRef} className="map" />
}
