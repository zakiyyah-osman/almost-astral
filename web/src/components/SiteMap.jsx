import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

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
export default function SiteMap({ data, layerState, selectedStop, onSelectStop, astronaut }) {
  const elRef = useRef(null)
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
      L.geoJSON(data.route, {
        coordsToLatLng: toLatLng,
        style: { color: '#ffffff', weight: 3, opacity: 0.9, dashArray: '6 6' },
      }).addTo(map)
    }
    if (data.waypoints) {
      let n = 0
      for (const f of data.waypoints.features) {
        const rover = f.properties.kind === 'rover'
        const marker = L.marker(toLatLng(f.geometry.coordinates), {
          icon: pinIcon(rover ? 'R' : ++n, rover),
          keyboard: false,
        })
          .bindTooltip(f.properties.name)
          .on('click', () => onSelect.current?.(f.properties.id))
          .addTo(map)
        markers.current[f.properties.id] = marker
      }
    }

    // The map's box changes size when the HUD opens or the window changes: refit it.
    const resize = new ResizeObserver(() => {
      map.invalidateSize()
      map.fitBounds(bounds)
    })
    resize.observe(elRef.current)

    mapRef.current = map
    return () => {
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
