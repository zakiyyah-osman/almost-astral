import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { buildTimeline, clock } from '../hud/sim.js'

// The site is a flat grid in metres, so we use Leaflet's CRS.Simple.
// A point at x metres east and y metres north is L.latLng(y, x): y comes first.
const toLatLng = (c) => L.latLng(c[1], c[0])

// Numbered pin: R for the rover, 1, 2, 3... for the science stops.
const pinIcon = (label, rover) =>
  L.divIcon({
    className: 'pin-icon',
    html: `<span class="pin${rover ? ' rover' : ''}">${label}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })

// `astronaut` is null, or { x, y, storm, trail } while the HUD simulation runs.
// `layoutKey` changes whenever the page layout changes the map's size (for example the HUD opens).
export default function SiteMap({ data, layerState, selectedStop, onSelectStop, astronaut, layoutKey }) {
  const elRef = useRef(null)
  const refit = useRef(() => {})
  const mapRef = useRef(null)
  const overlays = useRef({})
  const markers = useRef({})
  const astro = useRef({ marker: null, trail: null })
  const onSelect = useRef(onSelectStop)
  onSelect.current = onSelectStop

  useEffect(() => {
    const [w, h] = data.site.extent_m
    const bounds = [[0, 0], [h, w]]
    const map = L.map(elRef.current, {
      crs: L.CRS.Simple,
      minZoom: -3,
      maxZoom: 3,
      zoomSnap: 0.25,
      attributionControl: false,
    })
    map.createPane('layers').style.zIndex = 300 // below the route and markers
    map.fitBounds(bounds)
    L.control.scale({ imperial: false }).addTo(map)

    data.layers.forEach((layer, i) => {
      overlays.current[layer.id] = L.imageOverlay(`./${layer.file}`, bounds, { pane: 'layers', zIndex: i })
    })

    if (data.route) {
      // A dark casing under the dashed white line keeps the route readable on light terrain.
      L.geoJSON(data.route, {
        coordsToLatLng: toLatLng,
        interactive: false,
        style: { color: '#1a0e09', weight: 7, opacity: 0.7 },
      }).addTo(map)
      L.geoJSON(data.route, {
        coordsToLatLng: toLatLng,
        interactive: false,
        style: { color: '#ffffff', weight: 3, opacity: 0.95, dashArray: '6 6' },
      }).addTo(map)
    }
    if (data.waypoints) {
      // When each stop is reached, from the plan: shown on the map as T+hh:mm.
      const tl = buildTimeline(data.plan, data.waypoints, data.route)
      const arrival = {}
      for (const s of tl?.segments ?? []) if (s.type === 'walk') arrival[s.to] = s.t1
      let n = 0
      for (const f of data.waypoints.features) {
        const rover = f.properties.kind === 'rover'
        const label = rover
          ? `${f.properties.name} · start`
          : `${f.properties.name}${arrival[f.properties.id] != null ? ` · T+${clock(arrival[f.properties.id])}` : ''}`
        const marker = L.marker(toLatLng(f.geometry.coordinates), {
          icon: pinIcon(rover ? 'R' : ++n, rover),
          keyboard: false,
        })
          .bindTooltip(label, { permanent: true, direction: 'right', offset: [14, 0], className: 'stop-label' })
          .on('click', () => onSelect.current?.(f.properties.id))
          .addTo(map)
        markers.current[f.properties.id] = marker
      }
    }

    // The map's box changes size when the HUD opens or the window changes: refit it.
    // No animation and one refit after the resizing settles: an animated refit that
    // overlaps the next resize leaves the markers and the route out of step with the image.
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
      refit.current = () => {}
      resize.disconnect()
      map.remove()
      mapRef.current = null
      overlays.current = {}
      markers.current = {}
      astro.current = { marker: null, trail: null }
    }
  }, [data])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    for (const [id, state] of Object.entries(layerState)) {
      const overlay = overlays.current[id]
      if (!overlay) continue
      overlay.setOpacity(state.opacity)
      if (state.on && !map.hasLayer(overlay)) overlay.addTo(map)
      if (!state.on && map.hasLayer(overlay)) overlay.remove()
    }
  }, [layerState, data])

  useEffect(() => {
    refit.current()
  }, [layoutKey])

  // Highlight the selected stop.
  useEffect(() => {
    for (const [id, marker] of Object.entries(markers.current)) {
      marker.getElement()?.querySelector('.pin')?.classList.toggle('selected', id === selectedStop)
    }
  }, [selectedStop, data])

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
    const icon = L.divIcon({
      className: 'pin-icon',
      html: `<span class="astro${astronaut.storm ? ' storm' : ''}"></span>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    })
    if (!a.marker) {
      a.trail = L.polyline([], { color: colour, weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(map)
      a.marker = L.marker(latlng, { icon, zIndexOffset: 1000, interactive: false, keyboard: false }).addTo(map)
    }
    a.marker.setLatLng(latlng).setIcon(icon)
    a.trail.setStyle({ color: colour }).setLatLngs(astronaut.trail.map((p) => L.latLng(p[1], p[0])))
  }, [astronaut, data])

  return <div ref={elRef} className="map" />
}
