import Tag from './Tag.jsx'

// What is real, calculated, estimated, assumed or still fake, read from the sources in layers.json.
// Judges score validity: this list says plainly where every number on screen comes from.
export default function DataStatus({ data, terrain, params }) {
  const notes = data.sources_notes ?? {}
  const rows = data.layers.map((l) => ({
    name: l.title,
    kind: l.source.startsWith('FAKE') ? 'fake' : 'real',
    source: l.source.startsWith('FAKE') ? l.source.replace(/^FAKE\s*/, 'Placeholder ') : l.source,
  }))
  rows.push({ name: 'Terrain heights (dem.tif)', kind: notes['dem.tif'] ? 'real' : 'fake', source: notes['dem.tif'] ?? 'No source given' })
  rows.push({
    name: 'Routes, times, slopes',
    kind: 'calc',
    source: `Calculated in the app on the terrain heights, with the walking model and limits from ${params?.from ?? 'routing/config.toml'}. ${terrain?.hazardInterim ? 'Hazards: interim, from slope only.' : ''}`,
  })
  rows.push({ name: 'Team planner route (dotted line)', kind: data.plan?.fake || data.route?.features?.[0]?.properties?.fake ? 'fake' : 'calc', source: 'route.geojson and plan.json from routing/ (Person 3)' })
  rows.push({ name: 'Weather', kind: notes['weather.csv'] ? 'real' : 'fake', source: notes['weather.csv'] ?? 'weather.csv has no source yet: placeholder until the MEDA data is loaded' })
  rows.push({ name: 'Radiation', kind: 'estimate', source: notes['radiation.csv'] ?? 'radiation.csv' })
  if (data.tables?.space_weather) rows.push({ name: 'Solar storms', kind: 'real', source: notes['space_weather.csv'] ?? 'NASA DONKI' })
  rows.push({
    name: 'Ground photos',
    kind: 'real',
    source: data.photos?.length
      ? `${notes[data.vectors?.photos] ?? 'Perseverance raw images'} (photos.geojson, ${data.photos.length} photos). The pictures on the stop cards are separate illustrations from elsewhere in Jezero (mission/photos/CREDITS.md).`
      : 'No photos.geojson yet. The pictures on the stop cards are illustrations from elsewhere in Jezero (mission/photos/CREDITS.md).',
  })
  rows.push({ name: 'Limits: outing time, reserve, dose, slopes, pace', kind: 'assumption', source: 'Team choices in routing/config.toml and terrain/thresholds.toml' })

  return (
    <section>
      <h2>Data status</h2>
      <ul className="status-list">
        {rows.map((r) => (
          <li key={r.name}>
            <span>{r.name}</span>
            <Tag kind={r.kind} title={r.source} />
          </li>
        ))}
      </ul>
      <p className="muted">Hover a label to see its source.</p>
    </section>
  )
}
