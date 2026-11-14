// The 3D Mars globe on the homepage: Viking colour mosaic from NASA Mars Trek, one pulsing marker at
// the site centre, slow auto-rotation, drag to turn. It is lit by the real Sun: the light comes from
// the subsolar point at this moment (Mars24, lib/marsClock.js), so the day side, the night side and
// the terminator match the clock on the page. The light turns with the globe, because it is tied to
// the planet's surface, not to the screen. If WebGL or the imagery fails, it degrades to a
// plain rust sphere (or a CSS disc) instead of breaking the page.
import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { TREK_LAYERS } from '../lib/marsTrek.js'
import { marsTime, subsolarPoint } from '../lib/marsClock.js'

const DEG = Math.PI / 180
const RUST = 0xa4472a
// Viking MDIM 2.1 colour mosaic; zoom 2 of Mars Trek's EPSG:4326 grid is 8 x 4 tiles of 256 px (2048 x 1024).
const VIKING_URL = TREK_LAYERS.find((l) => l.id === 'viking').url
const ZOOM = 2
const COLS = 8
const ROWS = 4
const TILE = 256
const CAM_FAR = 4.2 // whole globe in view
const CAM_NEAR = 3.8 // card open: closer to the site (any nearer and the globe's edge leaves the canvas)
const NIGHT_LIGHT = 0.06 // faint ambient so the night side is very dark but its outline still shows (a display choice)

// Unit vector from the planet centre to the Sun, in the globe's own frame, for Earth time millis.
function sunDirection(millis) {
  const { lat, lonEast } = subsolarPoint(marsTime(millis))
  return surface(lat, lonEast, 1)
}

// Point on a radius-r sphere for three.js's SphereGeometry UV layout (lon 0 on +x, 90 E on -z).
function surface(lat, lonEast, r) {
  return new THREE.Vector3(
    r * Math.cos(lat * DEG) * Math.cos(lonEast * DEG),
    r * Math.sin(lat * DEG),
    -r * Math.cos(lat * DEG) * Math.sin(lonEast * DEG),
  )
}
// Globe rotation that puts (lat, lon) in front of a camera on +z.
const faceY = (lonEast) => -Math.PI / 2 - lonEast * DEG
const faceX = (lat) => lat * DEG

function loadTile(x, y) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous' // Mars Trek sends Access-Control-Allow-Origin: *
    img.onload = () => resolve({ img, x, y })
    img.onerror = () => reject(new Error(`tile ${x},${y}`))
    img.src = VIKING_URL.replace('{z}', ZOOM).replace('{y}', y).replace('{x}', x)
  })
}

// All 32 tiles stitched into one equirectangular canvas; rejects if any tile fails.
async function vikingCanvas() {
  const jobs = []
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) jobs.push(loadTile(x, y))
  const tiles = await Promise.all(jobs)
  const canvas = document.createElement('canvas')
  canvas.width = COLS * TILE
  canvas.height = ROWS * TILE
  const ctx = canvas.getContext('2d')
  for (const { img, x, y } of tiles) ctx.drawImage(img, x * TILE, y * TILE, TILE, TILE)
  return canvas
}

function glowTexture() {
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const g = c.getContext('2d')
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  grad.addColorStop(0, 'rgba(255, 214, 170, 1)')
  grad.addColorStop(0.18, 'rgba(255, 150, 100, 0.9)')
  grad.addColorStop(0.45, 'rgba(242, 138, 105, 0.35)')
  grad.addColorStop(1, 'rgba(242, 138, 105, 0)')
  g.fillStyle = grad
  g.fillRect(0, 0, 128, 128)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

// Soft orange rim of atmosphere: a slightly larger back-facing sphere, brighter towards the edge.
function atmosphere(sunUniform) {
  return new THREE.Mesh(
    new THREE.SphereGeometry(1.06, 64, 48),
    new THREE.ShaderMaterial({
      side: THREE.BackSide,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: `varying vec3 vN; void main() { vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      uniforms: { sunDir: sunUniform },
      // The rim only glows where sunlight reaches it, fading through the terminator.
      fragmentShader: `uniform vec3 sunDir; varying vec3 vN; void main() { float i = pow(0.62 - dot(vN, vec3(0.0, 0.0, 1.0)), 3.0); float day = smoothstep(-0.35, 0.35, dot(vN, sunDir)); gl_FragColor = vec4(0.95, 0.5, 0.32, 1.0) * i * (0.08 + 0.92 * day); }`,
    }),
  )
}

export default function Globe({ lat, lon, label, open, onSelect }) {
  const wrap = useRef(null)
  const labelRef = useRef(null)
  const openRef = useRef(open)
  const selectRef = useRef(onSelect)
  const [imagery, setImagery] = useState('loading') // loading | ok | failed
  const [webgl, setWebgl] = useState(true)
  const [labelVisible, setLabelVisible] = useState(true)
  openRef.current = open
  selectRef.current = onSelect

  useEffect(() => {
    const el = wrap.current
    if (!el || !Number.isFinite(lat) || !Number.isFinite(lon)) return undefined
    let renderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    } catch {
      setWebgl(false)
      return undefined
    }
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    el.appendChild(renderer.domElement)
    renderer.domElement.className = 'globe-canvas'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100)
    camera.position.set(0, 0, CAM_FAR)
    // Stars come from the page's Starfield behind the transparent canvas, so the sky has no square edge.
    // The Sun is far away: one directional light, aimed from the subsolar point every frame.
    scene.add(new THREE.AmbientLight(0xffffff, NIGHT_LIGHT))
    const sun = new THREE.DirectionalLight(0xfff1e6, 3.2)
    scene.add(sun)
    let sunLocal = sunDirection(Date.now())
    let sunCheckedAt = performance.now()
    const sunWorld = new THREE.Vector3()
    const sunUniform = { value: new THREE.Vector3() }

    const globe = new THREE.Group()
    scene.add(globe)
    const material = new THREE.MeshPhongMaterial({ color: RUST, shininess: 4 })
    const planet = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64), material)
    globe.add(planet)
    scene.add(atmosphere(sunUniform))

    // The marker: a bright core plus a pulsing glow sprite, just above the surface.
    const markerPos = surface(lat, lon, 1.004)
    const core = new THREE.Mesh(new THREE.SphereGeometry(0.014, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffd9b8 }))
    core.position.copy(markerPos)
    const glowTex = glowTexture()
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }))
    glow.position.copy(surface(lat, lon, 1.01))
    const ring = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }))
    ring.position.copy(glow.position)
    globe.add(core, glow, ring)

    let cancelled = false
    let settled = false // imagery loaded or failed: only then turn to the site, so the turn is seen
    vikingCanvas().finally(() => { settled = true }).then(
      (canvas) => {
        if (cancelled) return
        const tex = new THREE.CanvasTexture(canvas)
        tex.colorSpace = THREE.SRGBColorSpace
        tex.anisotropy = renderer.capabilities.getMaxAnisotropy()
        material.map = tex
        material.color.set(0xffffff)
        material.needsUpdate = true
        setImagery('ok')
      },
      () => !cancelled && setImagery('failed'),
    )

    // Rotation: start a third of a turn away; once the imagery is in, ease round to face the site,
    // hold there a few seconds, then drift slowly.
    const targetY = faceY(lon)
    const targetX = faceX(lat) * 0.85
    globe.rotation.set(targetX - 0.25, targetY + 2.1, 0)
    let intro = reduceMotion ? 0 : -1 // -1 = waiting for the imagery, 1 = turning, 0 = done
    if (reduceMotion) globe.rotation.set(targetX, targetY, 0)
    let lastUser = -Infinity
    let holdUntil = 0

    // Drag to rotate; a press that barely moves is a click (checked against the marker).
    let drag = null
    const canvas = renderer.domElement
    const ray = new THREE.Raycaster()
    const ndc = new THREE.Vector2()
    const onDown = (e) => {
      drag = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, id: e.pointerId }
      intro = 0
      settled = true
    }
    const onMove = (e) => {
      if (!drag || e.pointerId !== drag.id) return
      const dx = e.clientX - drag.x
      const dy = e.clientY - drag.y
      drag.x = e.clientX
      drag.y = e.clientY
      if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 4) canvas.setPointerCapture?.(e.pointerId)
      globe.rotation.y += dx * 0.006
      globe.rotation.x = Math.max(-1.2, Math.min(1.2, globe.rotation.x + dy * 0.006))
      lastUser = performance.now()
    }
    const onUp = (e) => {
      if (!drag) return
      const moved = Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy)
      drag = null
      if (moved > 5) return
      const r = canvas.getBoundingClientRect()
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      // Generous hit area: anything within ~4 % of the globe radius of the marker counts.
      const hit = ray.intersectObject(planet)[0]
      const world = core.getWorldPosition(new THREE.Vector3())
      if (hit && hit.point.distanceTo(world) < 0.09) selectRef.current?.()
    }
    const onCancel = () => { drag = null }
    canvas.addEventListener('pointerdown', onDown)
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup', onUp)
    canvas.addEventListener('pointercancel', onCancel)

    const resize = () => {
      const w = el.clientWidth
      const h = el.clientHeight
      if (!w || !h) return
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    const world = new THREE.Vector3()
    const normal = new THREE.Vector3()
    let shown = true
    let raf = 0
    let prev = performance.now()
    let wasOpen = false
    const tick = (now) => {
      const dt = Math.min(0.25, (now - prev) / 1000) // real seconds, so slow machines still arrive on time
      prev = now
      // Opening the card turns the globe back to the site (the shortest way round).
      if (openRef.current && !wasOpen) intro = 1
      wasOpen = openRef.current
      if (intro === -1 && settled) intro = 1
      if (intro > 0) {
        // Ease towards the site over about 2.5 s.
        const k = 1 - Math.exp(-dt * 2.2)
        const turn = 2 * Math.PI
        globe.rotation.y = targetY + ((((globe.rotation.y - targetY) % turn) + turn * 1.5) % turn) - turn / 2
        globe.rotation.y += (targetY - globe.rotation.y) * k
        globe.rotation.x += (targetX - globe.rotation.x) * k
        if (Math.abs(targetY - globe.rotation.y) < 0.002) {
          intro = 0
          holdUntil = now + 6000 // let people find the marker before the drift starts
        }
      } else if (intro === -1) {
        globe.rotation.y += dt * 0.05 // waiting for the imagery
      } else if (!reduceMotion && !drag && !openRef.current && now - lastUser > 4000 && now > holdUntil) {
        globe.rotation.y += dt * 0.05 // about one turn every two minutes
      }

      // Zoom in a little on the site while its card is open.
      const camZ = openRef.current ? CAM_NEAR : CAM_FAR
      camera.position.z = reduceMotion ? camZ : camera.position.z + (camZ - camera.position.z) * (1 - Math.exp(-dt * 3))

      const pulse = reduceMotion ? 0.5 : (Math.sin(now / 420) + 1) / 2
      glow.scale.setScalar(0.11 + 0.03 * pulse)
      const ringT = reduceMotion ? 0.5 : (now / 1800) % 1
      ring.scale.setScalar(0.08 + 0.22 * ringT)
      ring.material.opacity = 0.55 * (1 - ringT)

      // Mars turns 0.004 degrees a second, so updating the Sun once a second is plenty.
      if (now - sunCheckedAt > 1000) {
        sunLocal = sunDirection(Date.now())
        sunCheckedAt = now
      }
      sunWorld.copy(sunLocal).applyQuaternion(globe.quaternion)
      sun.position.copy(sunWorld).multiplyScalar(10)
      sunUniform.value.copy(sunWorld) // the camera is not rotated, so view space = world space here

      renderer.render(scene, camera)

      // Keep the HTML label next to the marker, hidden when the site is on the far side.
      core.getWorldPosition(world)
      normal.copy(world).normalize()
      const facing = normal.dot(camera.position.clone().sub(world).normalize()) > 0.2
      if (labelRef.current) {
        const p = world.clone().project(camera)
        labelRef.current.style.transform = `translate(${((p.x + 1) / 2) * el.clientWidth}px, ${((1 - p.y) / 2) * el.clientHeight}px)`
      }
      if (facing !== shown) {
        shown = facing
        setLabelVisible(facing)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onCancel)
      scene.traverse((o) => {
        o.geometry?.dispose?.()
        if (o.material) {
          o.material.map?.dispose?.()
          o.material.dispose?.()
        }
      })
      renderer.dispose()
      canvas.remove()
    }
  }, [lat, lon])

  return (
    <div className="globe" ref={wrap}>
      {!webgl && <div className="globe-fallback" aria-hidden="true" />}
      <div className={`globe-label${labelVisible || !webgl ? '' : ' away'}`} ref={labelRef}>
        <button type="button" className="globe-pin" onClick={onSelect} aria-expanded={open} aria-controls="site-card" tabIndex={labelVisible || !webgl ? 0 : -1}>
          <span className="globe-pin-dot" aria-hidden="true" />
          {label}
        </button>
      </div>
      <p className="globe-credit">
        {imagery === 'failed' || !webgl
          ? 'Globe imagery could not load: plain sphere shown.'
          : 'Globe: Viking MDIM 2.1 colour mosaic (NASA/USGS), tiles from NASA Mars Trek. Sunlit side calculated for right now (Mars24). Drag to turn.'}
      </p>
    </div>
  )
}
