import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { clock } from '../hud/sim.js'
import { graticule } from '../lib/graticule.js'

// The site is a flat grid in metres, so we use Leaflet's CRS.Simple.
// A point at x metres east and y metres north is L.latLng(y, x): y comes first.
const toLatLng = (c) => L.latLng(c[1], c[0])

const pinIcon = (label, kind, selected) =>
  L.divIcon({
    className: 'pin-icon',
    html: `<span class="pin ${kind}${selected ? ' selected' : ''}">${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })

// Props:
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
//  onHover      gets { x, y } under the pointer, or null
//  probe        { x, y }: a point to ring (from the profile chart)
//  astronaut    null, or { x, y, storm, trail } while the HUD simulation runs
//  layoutKey    changes whenever the page layout changes the map's size
export default function SiteMap({ data, extraLayers = [], layerState, route, refRoute, waypoints, arrivals, landing, missionPins, targets, picking, onPick, onInspect, inspect, gridOn, onView, onHover, probe, selectedStop, onSelectStop, astronaut, layoutKey, sizeKey }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const resizeOnly = useRef(() => {})
  const mapRef = useRef(null)
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

  // The map and the image layers: rebuilt only when the site itself changes.
  useEffect(() => {
    const [w, h] = data.site.extent_m
    const bounds = [[0, 0], [h, w]]
    const map = L.map(elRef.current, { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25, attributionControl: false })
    map.createPane('layers').style.zIndex = 300 // below the route and markers
    map.createPane('grid').style.zIndex = 350
    map.getPane('grid').style.pointerEvents = 'none'
    map.fitBounds(bounds)
    L.control.scale({ imperial: false }).addTo(map)
    data.layers.forEach((layer, i) => {
      overlays.current[layer.id] = L.imageOverlay(`./${layer.file}`, bounds, { pane: 'layers', zIndex: i })
    })
    groups.current = { grid: L.layerGroup().addTo(map), routes: L.layerGroup().addTo(map), targets: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) }

    map.on('click', (e) => {
      const { picking: p, onPick: pick, onInspect: insp } = cb.current
      const pt = { x: e.latlng.lng, y: e.latlng.lat }
      if (p && pick) pick(p, pt)
      else insp?.(pt)
    })
    map.on('moveend resize', () => {
      const c = map.getCenter()
      cb.current.onView?.({ centre: { x: c.lng, y: c.lat } })
      drawGrid.current()
    })
    let frame = 0
    map.on('mousemove', (e) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => cb.current.onHover?.({ x: e.latlng.lng, y: e.latlng.lat }))
    })
    map.on('mouseout', () => cb.current.onHover?.(null))

    // A new layout (HUD opened, visor, big text): refit the whole site, once, without animation.
    let timer = 0
    refit.current = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        map.invalidateSize({ animate: false })
        map.fitBounds(bounds, { animate: false })
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
    const [w, h] = data.site.extent_m
    for (const l of extraLayers) {
      if (!overlays.current[l.id] && l.url) overlays.current[l.id] = L.imageOverlay(l.url, [[0, 0], [h, w]], { pane: 'layers', zIndex: data.layers.length + 1 })
    }
    for (const [id, state] of Object.entries(layerState)) {
      const overlay = overlays.current[id]
      if (!overlay) continue
      overlay.setOpacity(state.opacity)
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

  // Latitude and longitude lines, redrawn whenever the map stops moving.
  useEffect(() => {
    const map = mapRef.current
    const g = groups.current.grid
    if (!map || !g) return
    const site = data.site
    drawGrid.current = () => {
      g.clearLayers()
      if (!gridOn || site.center_lat == null) return
      const b = map.getBounds()
      const view = { x0: b.getWest(), x1: b.getEast(), y0: b.getSouth(), y1: b.getNorth() }
      const { lats, lons, decimals } = graticule(view, site)
      const style = { pane: 'grid', color: '#f3e9e1', weight: 1, opacity: 0.22, interactive: false }
      const size = map.getSize()
      const at = (px, py) => map.containerPointToLatLng([px, py])
      for (const l of lats) {
        L.polyline([[l.y, view.x0], [l.y, view.x1]], style).addTo(g)
        const ll = at(4, 0)
        L.marker([l.y, ll.lng], { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lat', html: `${l.v.toFixed(decimals)}°N`, iconSize: null }) }).addTo(g)
      }
      for (const l of lons) {
        L.polyline([[view.y0, l.x], [view.y1, l.x]], style).addTo(g)
        const ll = at(0, 4)
        L.marker([ll.lat, l.x], { pane: 'grid', interactive: false, keyboard: false, icon: L.divIcon({ className: 'grid-label lon', html: `${l.v.toFixed(decimals)}°E`, iconSize: null }) }).addTo(g)
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
      L.geoJSON(refRoute, { coordsToLatLng: toLatLng, interactive: false, style: { color: '#c9b8ad', weight: 2, opacity: 0.8, dashArray: '2 6' } }).addTo(g)
    }
    if (route) {
      L.geoJSON(route, { coordsToLatLng: toLatLng, interactive: false, style: { color: '#1a0e09', weight: 7, opacity: 0.7 } }).addTo(g)
      L.geoJSON(route, { coordsToLatLng: toLatLng, interactive: false, style: { color: '#ffffff', weight: 3, opacity: 0.95, dashArray: '6 6' } }).addTo(g)
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
      L.marker(toLatLng(f.geometry.coordinates), { icon: pinIcon(rover ? 'R' : ++n, rover ? 'rover' : 'stop', f.properties.id === selectedStop), keyboard: false })
        .bindTooltip(label, { permanent: !missionPins?.length, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', pinClick(x, y, f.properties.name, f.properties.id))
        .addTo(g)
    }
    for (const s of landing ?? []) {
      L.marker(toLatLng([s.x, s.y]), { icon: pinIcon(s.label, 'landing', s.id === selectedStop), keyboard: false })
        .bindTooltip(s.title, { direction: 'top', offset: [0, -14], className: 'stop-label' })
        .on('click', pinClick(s.x, s.y, `${s.label} landing spot`, s.id))
        .addTo(g)
    }
    for (const p of missionPins ?? []) {
      L.marker(toLatLng([p.x, p.y]), { icon: pinIcon(p.label, p.kind), keyboard: false, zIndexOffset: 500 })
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
      L.marker(toLatLng([t.x, t.y]), { icon, keyboard: false })
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
    const ll = L.latLng(inspect.y, inspect.x)
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
    const ll = L.latLng(probe.y, probe.x)
    if (!probeDot.current) probeDot.current = L.circleMarker(ll, { radius: 9, color: '#ffffff', weight: 3, fillColor: '#e0714f', fillOpacity: 0.9, interactive: false }).addTo(map)
    else probeDot.current.setLatLng(ll)
  }, [probe, data])

  // The moving astronaut and the trail behind them.
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
    const latlng = L.latLng(astronaut.y, astronaut.x)
    const icon = L.divIcon({ className: 'pin-icon', html: `<span class="astro${astronaut.storm ? ' storm' : ''}"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] })
    if (!a.marker) {
      a.trail = L.polyline([], { color: colour, weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(map)
      a.marker = L.marker(latlng, { icon, zIndexOffset: 1000, interactive: false, keyboard: false }).addTo(map)
    }
    a.marker.setLatLng(latlng).setIcon(icon)
    a.trail.setStyle({ color: colour }).setLatLngs(astronaut.trail.map((p) => L.latLng(p[1], p[0])))
  }, [astronaut, data])

  return <div ref={elRef} className="map" />
}
