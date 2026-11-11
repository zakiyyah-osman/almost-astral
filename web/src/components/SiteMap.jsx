import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// The site is a flat grid in metres, so we use Leaflet's CRS.Simple.
// A point at x metres east and y metres north is L.latLng(y, x): y comes first.
const toLatLng = (c) => L.latLng(c[1], c[0])

export default function SiteMap({ data, layerState }) {
  const elRef = useRef(null)
  const mapRef = useRef(null)
  const overlays = useRef({})

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
        style: { color: '#ffffff', weight: 3, dashArray: '6 6' },
      }).addTo(map)
    }
    if (data.waypoints) {
      L.geoJSON(data.waypoints, {
        coordsToLatLng: toLatLng,
        pointToLayer: (f, latlng) =>
          L.circleMarker(latlng, {
            radius: f.properties.kind === 'rover' ? 9 : 7,
            color: '#ffffff',
            weight: 2,
            fillColor: f.properties.kind === 'rover' ? '#378add' : '#d85a30',
            fillOpacity: 1,
          }).bindTooltip(f.properties.name),
      }).addTo(map)
    }

    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      overlays.current = {}
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

  return <div ref={elRef} className="map" />
}
