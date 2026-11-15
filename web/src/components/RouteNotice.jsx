import { useEffect, useRef } from 'react'

// A notice that stays until dismissed (OK or Esc): a moved landing (lib/landingCheck.js messages) or a
// route that cannot be found (lib/routeFailure.js). The same text stays in the sidebar afterwards.
// It floats over the top of the map without blocking it: the next map click still picks a point.
// notice: { title, messages: [{ reason, title, detail }], footer? }
export default function RouteNotice({ notice, onClose }) {
  const ok = useRef(null)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])
  if (!notice) return null
  return (
    <div className="notice-float">
      <div className="landing-notice" role="alert" aria-labelledby="route-notice-title" aria-describedby="route-notice-body">
        <h2 id="route-notice-title">{notice.title}</h2>
        <div id="route-notice-body">
          <ul>
            {notice.messages.map((m) => (
              <li key={m.reason}>
                <b>{m.title}.</b> {m.detail}
              </li>
            ))}
          </ul>
          {notice.footer && <p className="moved">{notice.footer}</p>}
        </div>
        <button ref={ok} type="button" onClick={onClose}>
          OK
        </button>
      </div>
    </div>
  )
}
