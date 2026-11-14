import { useEffect, useRef } from 'react'

// The pop-up shown when a landing click was not safe and the spot was moved. Every sentence comes
// from routing's message templates (lib/landingCheck.js). It stays until dismissed (OK or Esc);
// the same messages stay in the sidebar afterwards.
export default function LandingNotice({ check, onClose }) {
  const ok = useRef(null)
  useEffect(() => {
    ok.current?.focus()
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])
  if (!check) return null
  return (
    <div className="notice-backdrop" onClick={onClose}>
      <div className="landing-notice" role="alertdialog" aria-modal="true" aria-labelledby="landing-notice-title" aria-describedby="landing-notice-body" onClick={(e) => e.stopPropagation()}>
        <h2 id="landing-notice-title">Not a safe place to land</h2>
        <div id="landing-notice-body">
          <ul>
            {check.messages.map((m) => (
              <li key={m.reason}>
                <b>{m.title}.</b> {m.detail}
              </li>
            ))}
          </ul>
          {check.moved_text && <p className="moved">{check.moved_text}</p>}
        </div>
        <button ref={ok} type="button" onClick={onClose}>
          OK
        </button>
      </div>
    </div>
  )
}
