// Full-page starry sky behind the homepage: twinkling stars in three depths that drift slightly with
// the pointer, and now and then a shooting star. Decoration only; still when reduced motion is on.
import { useEffect, useRef } from 'react'

const TINTS = ['255,255,255', '255,236,214', '214,226,255', '255,214,190']

function makeStars(w, h) {
  const n = Math.round((w * h) / 2400)
  return Array.from({ length: n }, () => {
    const depth = Math.random() // 0 far, 1 near
    return {
      x: Math.random() * w,
      y: Math.random() * h,
      r: 0.35 + depth * depth * 1.25,
      a: 0.25 + Math.random() * 0.6,
      depth,
      speed: 0.4 + Math.random() * 1.6,
      phase: Math.random() * Math.PI * 2,
      tint: TINTS[Math.random() < 0.7 ? 0 : 1 + Math.floor(Math.random() * 3)],
    }
  })
}

export default function Starfield() {
  const ref = useRef(null)

  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!ctx) return undefined
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let w = 0
    let h = 0
    let stars = []
    let shooting = null
    let nextShot = performance.now() + 3000
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 }

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      stars = makeStars(w, h)
      if (still) draw(0)
    }

    function draw(now) {
      ctx.clearRect(0, 0, w, h)
      pointer.x += (pointer.tx - pointer.x) * 0.04
      pointer.y += (pointer.ty - pointer.y) * 0.04
      for (const s of stars) {
        const tw = still ? 1 : 0.65 + 0.35 * Math.sin(now / 1000 * s.speed + s.phase)
        const x = (s.x - pointer.x * s.depth * 14 + w) % w
        const y = (s.y - pointer.y * s.depth * 10 + h) % h
        ctx.globalAlpha = s.a * tw
        ctx.fillStyle = `rgb(${s.tint})`
        ctx.beginPath()
        ctx.arc(x, y, s.r, 0, Math.PI * 2)
        ctx.fill()
        if (s.r > 1.2) {
          // a soft halo on the brightest stars
          ctx.globalAlpha = s.a * tw * 0.18
          ctx.beginPath()
          ctx.arc(x, y, s.r * 3, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      ctx.globalAlpha = 1

      if (still) return
      if (!shooting && now > nextShot) {
        const fromLeft = Math.random() < 0.5
        shooting = { x: fromLeft ? Math.random() * w * 0.5 : w * (0.5 + Math.random() * 0.5), y: Math.random() * h * 0.4, vx: (fromLeft ? 1 : -1) * (500 + Math.random() * 300), vy: 180 + Math.random() * 160, life: 0 }
      }
      if (shooting) {
        const s = shooting
        s.life += 1 / 60
        s.x += s.vx / 60
        s.y += s.vy / 60
        const fade = Math.max(0, 1 - s.life / 0.9)
        const grad = ctx.createLinearGradient(s.x, s.y, s.x - s.vx * 0.18, s.y - s.vy * 0.18)
        grad.addColorStop(0, `rgba(255,236,214,${0.9 * fade})`)
        grad.addColorStop(1, 'rgba(255,236,214,0)')
        ctx.strokeStyle = grad
        ctx.lineWidth = 1.4
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(s.x - s.vx * 0.18, s.y - s.vy * 0.18)
        ctx.stroke()
        if (fade === 0) {
          shooting = null
          nextShot = now + 6000 + Math.random() * 9000
        }
      }
    }

    let raf = 0
    const loop = (now) => {
      draw(now)
      raf = requestAnimationFrame(loop)
    }
    const onMove = (e) => {
      pointer.tx = e.clientX / window.innerWidth - 0.5
      pointer.ty = e.clientY / window.innerHeight - 0.5
    }

    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    if (!still) {
      window.addEventListener('pointermove', onMove)
      raf = requestAnimationFrame(loop)
    }
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      window.removeEventListener('pointermove', onMove)
    }
  }, [])

  return <canvas className="starfield" ref={ref} aria-hidden="true" />
}
