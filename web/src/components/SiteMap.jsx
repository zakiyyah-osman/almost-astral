import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { clock } from '../hud/sim.js'
import { graticule } from '../lib/graticule.js'
import { MARS_RADIUS_M, xyToLatLon, latLonToXY, lon180, siteBounds } from '../lib/geo.js'
import { TREK_LAYERS, TREK_ATTRIBUTION, CRATER } from '../lib/marsTrek.js'
import { squareBounds, classForPixel } from '../lib/research.js'

// Two ways to draw the site:
// - Real site (layers.json has site.center_lat / center_lon_east): a Mars map in latitude and
//   longitude (Leaflet EPSG4326, with the Mars radius so the scale bar is right), NASA Mars Trek
//   imagery underneath, and our 2 km square placed on it with geo.js. Start on the whole crater.
// - Fake site (no centre): the flat CRS.Simple grid, a point at (x, y) is L.latLng(y, x).
// Everything coming in and going out of this component stays in local site metres (x east, y north),
// so the route finder, the mission builder and the HUD do not change.

// Plain EPSG4326 draws a degree of longitude as wide as a degree of latitude, which at Jezero (18.5 N)
// stretches everything east-west by about 5% (cos 18.5 = 0.948), so the scale bar was only right
// east-west. Squeezing x by K = 243/256 (= cos 18.3 N) makes the map true to scale at the site to
// within 0.1%, and keeps every tile a whole number of pixels wide (256 -> 243, 512 -> 486): no seams.
const K = 243 / 256
const MARS_CRS = L.extend({}, L.CRS.EPSG4326, { R: MARS_RADIUS_M, transformation: new L.Transformation(K / 180, K, -1 / 180, 0.5) })
const squeezedTile = (size = 256) => L.point(Math.round(size * K), size)
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

// The Minerals layer: the site's own CRISM cells (minerals.png, 2 km) and the 12 km research areas
// (lib/research.js), under one switch. Both use the same five colours. Hovering a cell names its
// mineral; clicks go through to the map as usual (inspect a point, pick a mission point).
// setShown(ids) shows only the minerals picked in the list, in both images. Nothing is coloured until
// a mineral is picked.
function pixelsOf(url) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        ctx.drawImage(img, 0, 0)
        resolve({ ctx, w: canvas.width, h: canvas.height })
      } catch {
        resolve(null)
      }
    }
    img.onerror = () => resolve(null)
    img.src = url
  })
}

// A copy of an image keeping only the pixels of the given mineral classes, as a data URL.
function onlyClasses(pixels, ids) {
  const src = pixels.ctx.getImageData(0, 0, pixels.w, pixels.h)
  const d = new Uint8ClampedArray(src.data)
  for (let i = 0; i < d.length; i += 4) if (!ids.includes(classForPixel(d[i], d[i + 1], d[i + 2], d[i + 3])?.id)) d[i + 3] = 0
  const canvas = document.createElement('canvas')
  canvas.width = pixels.w
  canvas.height = pixels.h
  canvas.getContext('2d').putImageData(new ImageData(d, pixels.w, pixels.h), 0, 0)
  return canvas.toDataURL('image/png')
}

function mineralsLayer(layer, zIndex, siteBox, site, map) {
  const group = L.layerGroup()
  const parts = [] // { overlay, url, bounds, pixels, label }
  if (layer.file) {
    const url = `./${layer.file}`
    parts.push({ overlay: L.imageOverlay(BLANK_TILE, siteBox, { pane: 'layers', zIndex, className: 'mineral-cells' }), url, bounds: siteBox, label: '2 km site, CRISM' })
  }
  if (layer.research && site) {
    const b = squareBounds(site)
    const bounds = L.latLngBounds([b.south, b.west], [b.north, b.east])
    L.rectangle(bounds, { pane: 'research', interactive: false, fill: false, color: '#ffd166', weight: 1.5, opacity: 0.7, dashArray: '6 6' }).addTo(group)
    parts.push({ overlay: L.imageOverlay(BLANK_TILE, bounds, { pane: 'research', className: 'mineral-cells' }), url: layer.research.url, bounds, label: '12 km research' })
  }
  for (const p of parts) {
    p.overlay.addTo(group)
    pixelsOf(p.url).then((px) => {
      p.pixels = px
      draw(p)
    })
  }
  let shown = []
  const draw = (p) => {
    if (!p.pixels) return
    p.overlay.setUrl(shown.length ? onlyClasses(p.pixels, shown) : BLANK_TILE)
  }
  group.setShown = (ids) => {
    shown = ids ?? []
    parts.forEach(draw)
  }
  group.setOpacity = (o) => parts.forEach((p) => p.overlay.setOpacity(o))

  // The mineral under a point: the 12 km layer first (it is drawn on top), then the site's own cells.
  const classAt = (latlng) => {
    for (const p of [...parts].reverse()) {
      if (!p.pixels || !p.bounds.contains(latlng)) continue
      const fx = (latlng.lng - p.bounds.getWest()) / (p.bounds.getEast() - p.bounds.getWest())
      const fy = (p.bounds.getNorth() - latlng.lat) / (p.bounds.getNorth() - p.bounds.getSouth())
      const [r, g, bl, a] = p.pixels.ctx.getImageData(Math.min(p.pixels.w - 1, Math.floor(fx * p.pixels.w)), Math.min(p.pixels.h - 1, Math.floor(fy * p.pixels.h)), 1, 1).data
      const c = classForPixel(r, g, bl, a)
      if (c && c.areaKm2 != null && shown.includes(c.id)) return { c, label: p.label }
    }
    return null
  }
  const hoverTip = L.tooltip({ direction: 'top', offset: [0, -12], className: 'stop-label mineral-tip' })
  map.on('mousemove', (e) => {
    const hit = map.hasLayer(group) ? classAt(e.latlng) : null
    if (hit) {
      hoverTip.setLatLng(e.latlng).setContent(`<i style="background:${hit.c.color}"></i>${escapeHtml(hit.c.name)} <small>${hit.label}</small>`)
      if (!map.hasLayer(hoverTip)) hoverTip.addTo(map)
    } else if (map.hasLayer(hoverTip)) hoverTip.remove()
  })
  map.on('mouseout', () => map.hasLayer(hoverTip) && hoverTip.remove())
  return group
}

const pinIcon = (label, kind, selected) =>
  L.divIcon({
    className: 'pin-icon',
    html: `<span class="pin ${kind}${selected ? ' selected' : ''}">${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })

// A small Leaflet control holding a button.
function button(position, html, onClick) {
  const Ctl = L.Control.extend({
    onAdd() {
      const el = L.DomUtil.create('button', 'map-btn')
      el.type = 'button'
      el.innerHTML = html
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

// Props:
//  route        the active route (GeoJSON), drawn bold
//  refRoute     the team planner's route.geojson, drawn thin for comparison (or null)
//  waypoints    rover and stops; arrivals: { id: minutes } for the "T+hh:mm" labels
//  landing      recommended landing spots [{ x, y, label, title }]
//  missionPins  the custom mission's own points [{ x, y, label, kind, title }] (start, side quests, destination)
//  targets      mineral areas to pick as side quests [{ id, x, y, color, mineral, areaM2 }]
//  picking      'start' | 'quest' | 'dest' | null: the next map click (or pin click) sets that point (onPick)
//  onInspect    gets { x, y } when the map is clicked inside the site and nothing is being picked
//  inspect      { x, y }: the point being inspected, marked with a cross
//  gridOn       draw latitude and longitude lines for the part of the map on screen
//  onView       gets { centre: { x, y } } whenever the map stops moving
//  sizeKey      changes whenever the map's box changes size without a new layout (sidebar dragged)
//  onHover      gets { x, y } under the pointer (anywhere on the map, outside the site too), or null
//  probe        { x, y }: a point to ring (from the profile chart)
//  astronaut    null, or { x, y, storm, trail } while the HUD simulation runs
//  layoutKey    changes whenever the page layout changes the map's size
export default function SiteMap({ data, extraLayers = [], layerState, route, refRoute, waypoints, arrivals, landing, missionPins, targets, picking, onPick, onInspect, inspect, gridOn, onView, onHover, probe, selectedStop, onSelectStop, astronaut, layoutKey, sizeKey, mineralsShown = [] }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const resizeOnly = useRef(() => {})
  const mapRef = useRef(null)
  const geoRef = useRef(null)
  const focus = useRef('site') // 'crater' or 'site': what a layout change refits to
  const overlays = useRef({})
  const groups = useRef({})
  const astro = useRef({ marker: null, trail: null })
  const probeDot = useRef(null)
  const inspectMark = useRef(null)
  const drawGrid = useRef(() => {})
  const cb = useRef({})
  cb.current = { onSelectStop, onPick, onHover, onInspect, onView, picking }
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
    const inside = (ll) => site.contains(ll)

    const map = geo.real
      ? L.map(elRef.current, { crs: MARS_CRS, minZoom: 3, maxZoom: 18, zoomSnap: 0.25, wheelPxPerZoomLevel: 90, attributionControl: false, worldCopyJump: false })
      : L.map(elRef.current, { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25, attributionControl: false })
    map.createPane('craterLayers').style.zIndex = 290 // crater-wide layers sit under the site layers
    map.createPane('layers').style.zIndex = 300 // above the base tiles, below the route and markers
    map.createPane('research').style.zIndex = 320 // the 12 km mineral areas, above the site layers
    map.createPane('grid').style.zIndex = 350
    map.getPane('grid').style.pointerEvents = 'none'
    L.control.scale({ imperial: false }).addTo(map)

    const crater = geo.real ? craterBounds() : site
    const fit = (target, animate) => map.fitBounds(target === 'site' ? site : crater, { animate, padding: target === 'site' ? [12, 12] : [0, 0] })
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
          tileSize: squeezedTile(t.options?.tileSize), // drawn narrower to match MARS_CRS
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

      button('topright', 'Back to crater', () => flyTo('crater')).addTo(map)
      button('topright', 'Go to site', () => flyTo('site')).addTo(map)

      focus.current = 'crater'
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
      if (layer.id === 'minerals' && (layer.research || layer.file)) {
        overlays.current[layer.id] = mineralsLayer(layer, i, site, geo.real ? data.site : null, map)
        return
      }
      if (layer.file) overlays.current[layer.id] = L.imageOverlay(`./${layer.file}`, site, { pane: 'layers', zIndex: i })
    })
    groups.current = { grid: L.layerGroup().addTo(map), routes: L.layerGroup().addTo(map), targets: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) }

    map.on('click', (e) => {
      if (!inside(e.latlng)) return
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
      // Anywhere on the map, not only inside the site, so the pointer box reads out positions across the whole crater.
      frame = requestAnimationFrame(() => cb.current.onHover?.(geo.toXY(e.latlng)))
    })
    map.on('mouseout', () => cb.current.onHover?.(null))

    // A new layout (HUD opened, visor, big text): refit, once, without animation, to the site or the
    // crater, whichever was last chosen.
    let timer = 0
    refit.current = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        map.invalidateSize({ animate: false })
        fit(focus.current, false)
        drawGrid.current()
      }, 60)
    }
    refit.current.flyTo = flyTo
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

  // The minerals picked in the Minerals card: only those are coloured.
  useEffect(() => {
    overlays.current.minerals?.setShown?.(mineralsShown)
  }, [mineralsShown, data])

  useEffect(() => {
    refit.current()
  }, [layoutKey])

  useEffect(() => {
    resizeOnly.current()
  }, [sizeKey])

  // Latitude and longitude lines, redrawn whenever the map stops moving.
  useEffect(() => {
    const map = mapRef.current
    const g = groups.current.grid
    if (!map || !g) return
    const site = data.site
    const { toLL, toXY } = geoRef.current
    drawGrid.current = () => {
      g.clearLayers()
      if (!gridOn || site.center_lat == null) return
      const b = map.getBounds()
      const sw = toXY(b.getSouthWest())
      const ne = toXY(b.getNorthEast())
      const view = { x0: sw.x, x1: ne.x, y0: sw.y, y1: ne.y }
      const { lats, lons, decimals } = graticule(view, site)
      const style = { pane: 'grid', color: '#f3e9e1', weight: 1, opacity: 0.22, interactive: false }
      const at = (px, py) => map.containerPointToLatLng([px, py])
      for (const l of lats) {
        L.polyline([toLL(view.x0, l.y), toLL(view.x1, l.y)], style).addTo(g)
        L.marker([toLL(0, l.y).lat, at(4, 0).lng], { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lat', html: `${l.v.toFixed(decimals)}°N`, iconSize: null }) }).addTo(g)
      }
      for (const l of lons) {
        L.polyline([toLL(l.x, view.y0), toLL(l.x, view.y1)], style).addTo(g)
        L.marker([at(0, 4).lat, toLL(l.x, 0).lng], { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lon', html: `${l.v.toFixed(decimals)}°E`, iconSize: null }) }).addTo(g)
      }
    }
    drawGrid.current()
  }, [gridOn, data])

  // Routes: the team planner's route thin underneath, the active route bold on top.
  useEffect(() => {
    const g = groups.current.routes
    if (!g) return
    const toLL = (c) => geoRef.current.toLL(c[0], c[1])
    g.clearLayers()
    if (refRoute) {
      L.geoJSON(refRoute, { coordsToLatLng: toLL, interactive: false, style: { color: '#c9b8ad', weight: 2, opacity: 0.8, dashArray: '2 6' } }).addTo(g)
    }
    if (route) {
      L.geoJSON(route, { coordsToLatLng: toLL, interactive: false, style: { color: '#1a0e09', weight: 7, opacity: 0.7 } }).addTo(g)
      L.geoJSON(route, { coordsToLatLng: toLL, interactive: false, style: { color: '#ffffff', weight: 3, opacity: 0.95, dashArray: '6 6' } }).addTo(g)
    }
  }, [route, refRoute, data])

  // Pins: rover and stops, landing suggestions, the custom mission's own points.
  useEffect(() => {
    const g = groups.current.pins
    if (!g) return
    const { toLL } = geoRef.current
    g.clearLayers()
    let n = 0
    for (const f of waypoints?.features ?? []) {
      const kind = f.properties.kind
      if (kind !== 'rover' && kind !== 'stop') continue
      const rover = kind === 'rover'
      const t = arrivals?.[f.properties.id]
      const label = rover ? `${f.properties.name} · start` : `${f.properties.name}${t != null ? ` · T+${clock(t)}` : ''}`
      const [x, y] = f.geometry.coordinates
      L.marker(toLL(x, y), { icon: pinIcon(rover ? 'R' : ++n, rover ? 'rover' : 'stop', f.properties.id === selectedStop), keyboard: false })
        .bindTooltip(label, { permanent: !missionPins?.length, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', pinClick(x, y, f.properties.name, f.properties.id))
        .addTo(g)
    }
    for (const s of landing ?? []) {
      L.marker(toLL(s.x, s.y), { icon: pinIcon(s.label, 'landing', s.id === selectedStop), keyboard: false })
        .bindTooltip(s.title, { direction: 'top', offset: [0, -14], className: 'stop-label' })
        .on('click', pinClick(s.x, s.y, `${s.label} landing spot`, s.id))
        .addTo(g)
    }
    for (const p of missionPins ?? []) {
      L.marker(toLL(p.x, p.y), { icon: pinIcon(p.label, p.kind), keyboard: false, zIndexOffset: 500 })
        .bindTooltip(p.title, { permanent: true, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', pinClick(p.x, p.y, p.name))
        .addTo(g)
    }
  }, [waypoints, arrivals, landing, missionPins, selectedStop, data])

  // Mineral areas that can be picked as side quests: small diamonds in the mineral's colour.
  useEffect(() => {
    const g = groups.current.targets
    if (!g) return
    const { toLL } = geoRef.current
    g.clearLayers()
    for (const t of targets ?? []) {
      const icon = L.divIcon({ className: 'pin-icon', html: `<span class="target" style="--c:${t.color}"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] })
      L.marker(toLL(t.x, t.y), { icon, keyboard: false })
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
    const ll = geoRef.current.toLL(inspect.x, inspect.y)
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
    const { toLL, real } = geoRef.current
    const colour = astronaut.storm ? '#ff6b57' : '#5eead4'
    const latlng = toLL(astronaut.x, astronaut.y)
    const icon = L.divIcon({ className: 'pin-icon', html: `<span class="astro${astronaut.storm ? ' storm' : ''}"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] })
    if (!a.marker) {
      if (real && focus.current !== 'site') refit.current.flyTo?.('site')
      a.trail = L.polyline([], { color: colour, weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(map)
      a.marker = L.marker(latlng, { icon, zIndexOffset: 1000, interactive: false, keyboard: false }).addTo(map)
    }
    a.marker.setLatLng(latlng).setIcon(icon)
    a.trail.setStyle({ color: colour }).setLatLngs(astronaut.trail.map((p) => toLL(p[0], p[1])))
  }, [astronaut, data])

  return <div ref={elRef} className="map" />
}
