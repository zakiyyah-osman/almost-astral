import Icon from './Icon.jsx'
import Tag from './Tag.jsx'

const fmtXY = (p) => `x ${Math.round(p.x)} m, y ${Math.round(p.y)} m`

// The landing check's result under the Landing row: the status and every message, from routing's
// templates. It stays after the pop-up for a moved landing is closed.
function LandingStatus({ landing }) {
  if (!landing) return null
  const cls = { safe: 'ok', marginal: 'warn', moved: 'moved', outside: 'bad' }[landing.status]
  const head = { safe: null, marginal: 'Marginal landing spot', moved: 'Moved to a safe spot', outside: null }[landing.status]
  return (
    <div className={`landing-status ${cls}`} role="status">
      {head && <b>{head}</b>}
      <ul>
        {landing.messages.map((m) => (
          <li key={m.reason}>
            <b>{m.title}.</b> {m.detail}
          </li>
        ))}
      </ul>
      {landing.moved_text && <p>{landing.moved_text}</p>}
      {landing.warnings?.length > 0 && <p className="muted">Warning: {landing.warnings.join(', ').replaceAll('_', ' ')}.</p>}
    </div>
  )
}

// A custom mission: a landing, side quests in visiting order, and the final destination.
// The landing is chosen on the map and checked against routing's landing rules (lib/landingCheck.js);
// the other points can be picked on the map (a click, or a click on a pin) or from the list of named places.
export default function MissionBuilder({ landing, landingReady, mission, setMission, picking, setPicking, places, detours, targets, onBestOrder, defaultStopMin, mineralNote }) {
  const { start, quests, dest } = mission
  const set = (patch) => setMission((m) => ({ ...m, ...patch }))
  const setQuest = (k, patch) => setMission((m) => ({ ...m, quests: m.quests.map((q, j) => (j === k ? { ...q, ...patch } : q)) }))
  const moveQuest = (k, by) =>
    setMission((m) => {
      const q = m.quests.slice()
      const j = k + by
      if (j < 0 || j >= q.length) return m
      ;[q[k], q[j]] = [q[j], q[k]]
      return { ...m, quests: q }
    })
  const fromPlace = (which, id) => {
    const p = places.find((q) => q.id === id)
    if (!p) return
    const pt = { x: p.x, y: p.y, name: p.name }
    if (which === 'quest') setMission((m) => ({ ...m, quests: [...m.quests, { ...pt, stopMin: defaultStopMin }] }))
    else set({ [which]: which === 'dest' ? { ...pt, name: dest?.name && dest.name !== 'J0' ? dest.name : pt.name } : pt })
  }
  const added = (t) => quests.some((q) => Math.abs(q.x - t.x) < 1 && Math.abs(q.y - t.y) < 1)

  const pickButton = (which, children) => (
    <button type="button" className={`pick${picking === which ? ' active' : ''}`} aria-pressed={picking === which} onClick={() => setPicking(picking === which ? null : which)}>
      <Icon name="target" size={14} />
      {picking === which ? (which === 'quest' ? 'Done' : 'Click the map') : children}
    </button>
  )

  const placeSelect = (which, label) => (
    <select value="" onChange={(e) => fromPlace(which, e.target.value)} aria-label={label}>
      <option value="">{label}…</option>
      {places.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  )

  return (
    <div className="mission">
      <div className="mrow">
        <span className={`pin landing-${landing?.status === 'marginal' ? 'marginal' : 'safe'}`}>L</span>
        <div className="mrow-main">
          <b>Landing</b>
          <small>{start ? fmtXY(start) : landingReady ? 'Click the map to choose a landing site' : 'Loading the landing map…'}</small>
        </div>
        {landingReady && pickButton('landing', start ? 'Move' : 'On map')}
      </div>
      <LandingStatus landing={landing} />

      <div className="quests-head">
        <h3>
          Side quests <span className="count">{quests.length}</span>
        </h3>
        <button type="button" className="link" onClick={onBestOrder} disabled={quests.length < 2 || !start || !dest} title="Visit the side quests in the order with the least walking">
          <Icon name="sort" size={14} /> Best order
        </button>
      </div>
      {quests.length === 0 && <p className="muted">Optional stops on the way, such as a mineral area to sample. Add them on the map, from a place, or from the mineral areas below.</p>}
      <ol className="quest-list">
        {quests.map((q, k) => {
          const d = detours?.[k]
          return (
            <li key={`${q.x}-${q.y}-${k}`}>
              <span className="pin quest">{k + 1}</span>
              <div className="mrow-main">
                <b title={q.name}>{q.name}</b>
                <small>
                  {d ? (
                    <>
                      +{Math.round(d.min)} min · +{Math.round(d.m)} m · +{Math.round(d.dose)} µSv
                    </>
                  ) : start && dest ? (
                    'cost not available'
                  ) : (
                    'set start and destination'
                  )}
                </small>
              </div>
              <label className="mins" title="Minutes on site">
                <input type="number" min="0" max="120" step="5" value={q.stopMin ?? defaultStopMin} onChange={(e) => setQuest(k, { stopMin: Math.max(0, Math.min(120, Number(e.target.value) || 0)) })} aria-label={`Minutes at ${q.name}`} />
                <span>min</span>
              </label>
              <div className="row-tools">
                <button type="button" onClick={() => moveQuest(k, -1)} disabled={k === 0} aria-label={`Move ${q.name} earlier`}>
                  <Icon name="up" size={14} />
                </button>
                <button type="button" onClick={() => moveQuest(k, 1)} disabled={k === quests.length - 1} aria-label={`Move ${q.name} later`}>
                  <Icon name="down" size={14} />
                </button>
                <button type="button" onClick={() => setMission((m) => ({ ...m, quests: m.quests.filter((_, j) => j !== k) }))} aria-label={`Remove ${q.name}`}>
                  <Icon name="close" size={14} />
                </button>
              </div>
            </li>
          )
        })}
      </ol>
      <div className="two-up">
        {pickButton('quest', 'Add on map')}
        {placeSelect('quest', 'Add a place')}
      </div>

      {targets?.length > 0 && (
        <details className="targets" open={quests.length === 0}>
          <summary>
            Mineral areas near the route <Tag kind="real" title={mineralNote} />
          </summary>
          <ul>
            {targets.map((t) => (
              <li key={t.id}>
                <i className="swatch-dot" style={{ background: t.color }} />
                <span>
                  <b>{t.mineral}</b>
                  <small>
                    {Math.round(t.areaM2).toLocaleString()} m² · {t.detourMin == null ? 'set start and destination' : t.detourMin < 1 ? 'on the route' : `about ${Math.round(t.detourMin)} min off the route, there and back`}
                  </small>
                </span>
                <button type="button" disabled={added(t)} onClick={() => setMission((m) => ({ ...m, quests: [...m.quests, { x: t.x, y: t.y, name: `${t.mineral} area`, stopMin: defaultStopMin }] }))}>
                  {added(t) ? 'Added' : 'Add'}
                </button>
              </li>
            ))}
          </ul>
          <p className="muted">CRISM pixels are about 18 m, so these are areas to search, not single rocks. The crew confirms the mineral on site.</p>
        </details>
      )}

      <div className="mrow">
        <span className="pin m-dest">{(dest?.name || 'J0').slice(0, 2)}</span>
        <div className="mrow-main">
          <b>Destination</b>
          <small>{dest ? fmtXY(dest) : 'Not set'}</small>
        </div>
        {pickButton('dest', 'On map')}
      </div>
      <div className="two-up">
        <input className="text" value={dest?.name ?? ''} placeholder="Name, e.g. J0" disabled={!dest} onChange={(e) => set({ dest: { ...dest, name: e.target.value } })} aria-label="Destination name" />
        {placeSelect('dest', 'Pick a place')}
      </div>

      <p className="muted">One way: the walk ends at the destination. The time needed counts the walk, {defaultStopMin} min there (or what you set), the minutes at each side quest and getting into the lander.</p>
    </div>
  )
}
