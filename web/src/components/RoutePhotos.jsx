// Real Perseverance ground photos for the planned walk, from Yaj's helpers in lib/photos.js:
// - the photo nearest the destination, shown only when it was taken close enough to stand for it
//   (describeNearest; otherwise it says how far the nearest one is);
// - "Along your walk": photos taken within 100 m of the route, in the order the walk meets them.
// Positions are site metres; photos are latitude/longitude, so points go through geo.js first.
import { useMemo } from 'react'
import { xyToLatLon } from '../lib/geo.js'
import { describeNearest, nearestPhoto, photosAlongPath } from '../lib/photos.js'
import Tag from './Tag.jsx'

const ALONG_M = 100
const MAX_SHOWN = 8

export default function RoutePhotos({ site, dest, route }) {
  const coords = route?.features?.[0]?.geometry?.coordinates
  const near = useMemo(() => {
    if (!dest || site?.center_lat == null) return null
    const ll = xyToLatLon(dest.x, dest.y, site)
    const r = nearestPhoto(ll.lat, ll.lon)
    return r ? { ...r, ...describeNearest(r) } : null
  }, [dest, site])
  const along = useMemo(() => {
    if (!coords?.length || site?.center_lat == null) return []
    return photosAlongPath(coords.map(([x, y]) => xyToLatLon(x, y, site)), ALONG_M)
  }, [coords, site])

  if (!near && !along.length) return null
  return (
    <details className="more route-photos">
      <summary>
        Photos along the route <Tag kind="real" title="NASA/JPL-Caltech Perseverance raw images; position from the rover's traverse on the day each was taken" />
      </summary>
      {near && (
        <div className="rp-near">
          <b>At {dest.name || 'the destination'}</b>
          {near.show ? (
            <a href={near.photo.url} target="_blank" rel="noreferrer" className="rp-thumb wide">
              <img src={near.photo.url} alt={`Perseverance ${near.photo.camera}, sol ${near.photo.sol}`} loading="lazy" />
            </a>
          ) : null}
          <small>{near.text}</small>
        </div>
      )}
      {along.length > 0 && (
        <div className="rp-along">
          <b>
            Along your walk <small>({along.length} within {ALONG_M} m of the route)</small>
          </b>
          <div className="rp-strip">
            {along.slice(0, MAX_SHOWN).map(({ photo, along_m: a }) => (
              <a key={photo.image_id} href={photo.url} target="_blank" rel="noreferrer" className="rp-thumb" title={`Sol ${photo.sol}, ${photo.camera}. Credit: ${photo.credit}`}>
                <img src={photo.url} alt={`Perseverance ${photo.camera}, sol ${photo.sol}`} loading="lazy" />
                <span>{a >= 1000 ? `${(a / 1000).toFixed(1)} km` : `${Math.round(a / 10) * 10} m`}</span>
              </a>
            ))}
          </div>
          <small>Distance along the walk. Credit: NASA/JPL-Caltech (Mastcam-Z: NASA/JPL-Caltech/ASU).</small>
        </div>
      )}
    </details>
  )
}
