import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { clock } from '../hud/sim.js'

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
//  ends         custom route ends { start: {x, y}, end: {x, y} } (either may be missing)
//  picking      'start' | 'end' | null: the next map click sets that point (onPick)
//  onHover      gets { x, y } under the pointer, or null
//  probe        { x, y }: a point to ring (from the profile chart)
//  astronaut    null, or { x, y, storm, trail } while the HUD simulation runs
//  layoutKey    changes whenever the page layout changes the map's size
export default function SiteMap({ data, extraLayers = [], layerState, route, refRoute, waypoints, arrivals, landing, ends, picking, onPick, onHover, probe, selectedStop, onSelectStop, astronaut, layoutKey }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const mapRef = useRef(null)
  const overlays = useRef({})
  const groups = useRef({})
  const astro = useRef({ marker: null, trail: null })
  const probeDot = useRef(null)
  const cb = useRef({})
  cb.current = { onSelectStop, onPick, onHover, picking }

  // The map and the image layers: rebuilt only when the site itself changes.
  useEffect(() => {
    const [w, h] = data.site.extent_m
    const bounds = [[0, 0], [h, w]]
    const map = L.map(elRef.current, { crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, zoomSnap: 0.25, attributionControl: false })
    map.createPane('layers').style.zIndex = 300 // below the route and markers
    map.fitBounds(bounds)
    L.control.scale({ imperial: false }).addTo(map)
    data.layers.forEach((layer, i) => {
      overlays.current[layer.id] = L.imageOverlay(`./${layer.file}`, bounds, { pane: 'layers', zIndex: i })
    })
    groups.current = { routes: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) }

    map.on('click', (e) => {
      const { picking: p, onPick: pick } = cb.current
      if (p && pick) pick(p, { x: e.latlng.lng, y: e.latlng.lat })
    })
    let frame = 0
    map.on('mousemove', (e) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => cb.current.onHover?.({ x: e.latlng.lng, y: e.latlng.lat }))
    })
    map.on('mouseout', () => cb.current.onHover?.(null))

    // The map's box changes size when the HUD opens or the window changes: refit it, once, without animation.
    let timer = 0
    refit.current = () => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        map.invalidateSize({ animate: false })
        map.fitBounds(bounds, { animate: false })
      }, 60)
    }
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
      L.marker(toLatLng(f.geometry.coordinates), { icon: pinIcon(rover ? 'R' : ++n, rover ? 'rover' : 'stop', f.properties.id === selectedStop), keyboard: false })
        .bindTooltip(label, { permanent: true, direction: 'right', offset: [14, 0], className: 'stop-label' })
        .on('click', () => cb.current.onSelectStop?.(f.properties.id))
        .addTo(g)
    }
    for (const s of landing ?? []) {
      L.marker(toLatLng([s.x, s.y]), { icon: pinIcon(s.label, 'landing'), keyboard: false })
        .bindTooltip(s.title, { direction: 'top', offset: [0, -14], className: 'stop-label' })
        .on('click', () => cb.current.onSelectStop?.(s.id))
        .addTo(g)
    }
    for (const [key, label] of [['start', 'A'], ['end', 'B']]) {
      const p = ends?.[key]
      if (p) L.marker(toLatLng([p.x, p.y]), { icon: pinIcon(label, `end-${key}`), keyboard: false, interactive: false }).addTo(g)
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
