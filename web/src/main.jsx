import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Home from './home/Home.jsx'

// The homepage by default, the map at #map. A plain link to #map adds a history entry,
// so Back returns to the homepage, and a direct link to /#map skips it.
// #map?photo=<id> opens the map on that ground photo (App then trims the hash back to #map).
function route(hash) {
  if (hash === '#map') return { map: true, photo: null }
  if (hash.startsWith('#map?')) return { map: true, photo: new URLSearchParams(hash.slice(5)).get('photo') }
  return { map: false, photo: null }
}

function Root() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onHash = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const r = route(hash)
  return r.map ? <App focusPhoto={r.photo} /> : <Home />
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
