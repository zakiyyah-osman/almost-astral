// The list under the map for the 12 km mineral research: each mineral's colour and mapped area,
// the rover sample symbols, and where every number comes from (lib/research.js).
import { useState } from 'react'
import { RESEARCH, MINERAL_CLASSES, NO_DATA, CHECKED_UNMAPPED, REFERENCES, MARKERS } from '../lib/research.js'

// Remembers whether the list was hidden. Browser storage can be blocked: then it just starts open.
const KEY = 'aa.mineralKeyOpen'
const readOpen = () => {
  try {
    return localStorage.getItem(KEY) !== '0'
  } catch {
    return true
  }
}

export default function MineralKey({ hasMap }) {
  const [open, setOpenState] = useState(readOpen)
  const setOpen = (f) =>
    setOpenState((o) => {
      const next = f(o)
      try {
        localStorage.setItem(KEY, next ? '1' : '0')
      } catch {
        /* not stored */
      }
      return next
    })
  const [sources, setSources] = useState(false)
  const samples = MARKERS.filter((m) => m.kind === 'star').length
  return (
    <section className={`mineral-key${open ? '' : ' shut'}`} aria-label="Minerals in the 12 km square">
      <header>
        <button type="button" className="mk-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <b>Minerals · 12 km × 12 km</b>
          <span>{open ? 'Hide' : 'Show'}</span>
        </button>
      </header>
      {open && (
        <>
          <ul className="mk-list">
            {MINERAL_CLASSES.map((c) => (
              <li key={c.id} title={c.about}>
                <i style={{ background: c.color }} />
                <span>{c.name}</span>
                <small>{c.areaKm2} km²</small>
              </li>
            ))}
            <li title={NO_DATA.about}>
              <i style={{ background: NO_DATA.color }} />
              <span>{NO_DATA.name}</span>
              <small>{NO_DATA.percent}% of square</small>
            </li>
            <li>
              <span className="research-mark star" aria-hidden="true" />
              <span>Perseverance sample site ({samples})</span>
            </li>
            <li>
              <span className="research-mark landing" aria-hidden="true" />
              <span>Perseverance landing site</span>
            </li>
          </ul>
          <p className="mk-note">
            {hasMap ? 'Click a coloured area or a star for details. ' : 'Colour layer coming from the data lead; click a star for details. '}
            Relative CRISM signals, not confirmed detections. Amounts in tonnes are not known from orbit. {CHECKED_UNMAPPED}
          </p>
          <button type="button" className="link" onClick={() => setSources((s) => !s)} aria-expanded={sources}>
            {sources ? 'Hide sources' : `Sources: “${RESEARCH.title}”`}
          </button>
          {sources && (
            <div className="mk-sources">
              <p>
                Team research note, {RESEARCH.author}, {RESEARCH.date} ({RESEARCH.file}). {RESEARCH.caption}
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
        </>
      )}
    </section>
  )
}
