// The mineral switches inside the Minerals layer card (left panel). Each mineral is off until you
// switch it on; only the minerals switched on are coloured on the map (in the 2 km site cells and the
// 12 km research areas alike). Sources lists the references behind the research note (lib/research.js).
import { useState } from 'react'
import { RESEARCH, MINERAL_CLASSES, NO_DATA, CHECKED_UNMAPPED, REFERENCES } from '../lib/research.js'

export default function MineralKey({ shown, onChange, traced }) {
  const [sources, setSources] = useState(false)
  const toggle = (id) => onChange(shown.includes(id) ? shown.filter((k) => k !== id) : [...shown, id])
  const all = shown.length === MINERAL_CLASSES.length
  return (
    <div className="mineral-key">
      <div className="mk-head">
        <span>{shown.length ? `${shown.length} of ${MINERAL_CLASSES.length} shown` : 'Pick the minerals to show'}</span>
        <button type="button" className="link" onClick={() => onChange(all ? [] : MINERAL_CLASSES.map((c) => c.id))}>
          {all ? 'Hide all' : 'Show all'}
        </button>
      </div>
      <ul className="mk-list" aria-label="Minerals to show on the map">
        {MINERAL_CLASSES.map((c) => {
          const on = shown.includes(c.id)
          return (
            <li key={c.id}>
              <button type="button" className={on ? 'on' : ''} role="switch" aria-checked={on} title={c.about} onClick={() => toggle(c.id)}>
                <i style={{ background: c.color }} />
                <span>{c.name}</span>
                <small>{c.areaKm2} km²</small>
              </button>
            </li>
          )
        })}
      </ul>
      <p className="mk-note">
        Areas are for the 12 km square (dashed outline); hover a coloured cell to name it. Relative CRISM signals, not confirmed detections;
        tonnes are not known from orbit. {NO_DATA.name} over about {NO_DATA.percent}% of the square. {CHECKED_UNMAPPED}
        {traced && ' The 12 km areas are traced from the research note’s map, good to about 20–30 m.'}
      </p>
      <button type="button" className="link" onClick={() => setSources((s) => !s)} aria-expanded={sources}>
        {sources ? 'Hide sources' : `Sources (${Object.keys(REFERENCES).length})`}
      </button>
      {sources && (
        <div className="mk-sources">
          <p>
            “{RESEARCH.title}”, {RESEARCH.author}, {RESEARCH.date} ({RESEARCH.file}).
          </p>
          <ol>
            {Object.entries(REFERENCES).map(([id, r]) => (
              <li key={id}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.label}
                </a>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
