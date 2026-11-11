import { useEffect, useState } from 'react'
import SiteMap from './components/SiteMap.jsx'
import HudView from './hud/HudView.jsx'
import { loadData } from './lib/loadData.js'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [layerState, setLayerState] = useState({})
  const [view, setView] = useState('planning')

  useEffect(() => {
    loadData()
      .then((d) => {
        setData(d)
        setLayerState(
          Object.fromEntries(d.layers.map((l) => [l.id, { on: !!l.default, opacity: l.opacity ?? 1 }])),
        )
      })
      .catch((e) => setError(e.message))
  }, [])

  const update = (id, patch) => setLayerState((s) => ({ ...s, [id]: { ...s[id], ...patch } }))

  if (error) return <p className="status">Could not load the data: {error}</p>
  if (!data) return <p className="status">Loading…</p>

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Martian Map</h1>
        <p className="muted">Almost Astral · NASA Space Apps</p>
        <p className="muted">{data.site.name}</p>

        <div className="views">
          <button className={view === 'planning' ? 'active' : ''} onClick={() => setView('planning')}>
            Planning
          </button>
          <button className={view === 'hud' ? 'active' : ''} onClick={() => setView('hud')}>
            HUD
          </button>
        </div>

        <h2>Layers</h2>
        {data.layers.map((l) => (
          <div key={l.id} className="layer">
            <label>
              <input type="checkbox" checked={layerState[l.id]?.on ?? false} onChange={(e) => update(l.id, { on: e.target.checked })} />
              <span>
                {l.title}
                <small>{l.source}</small>
              </span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={layerState[l.id]?.opacity ?? 1}
              onChange={(e) => update(l.id, { opacity: Number(e.target.value) })}
              aria-label={`${l.title} opacity`}
            />
          </div>
        ))}

        {data.plan && (
          <>
            <h2>Plan</h2>
            <p className="muted">
              {data.plan.totals.total_min} min total · {data.plan.radiation_dose_usv} µSv
            </p>
          </>
        )}
      </aside>

      <main>
        <SiteMap data={data} layerState={layerState} />
        {view === 'hud' && <HudView data={data} />}
      </main>
    </div>
  )
}
