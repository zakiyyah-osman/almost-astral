import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createReadStream, cpSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

// The stop photos live in mission/photos. Serve them at ./photos/<file> in dev and copy the images into the build.
const PHOTOS = fileURLToPath(new URL('../mission/photos', import.meta.url))
const TYPES = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp' }

function missionPhotos() {
  let outDir = 'dist'
  return {
    name: 'mission-photos',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir)
    },
    configureServer(server) {
      server.middlewares.use('/photos', (req, res, next) => {
        let name
        try {
          name = decodeURIComponent((req.url ?? '').split('?')[0])
        } catch {
          return next()
        }
        const file = join(PHOTOS, name)
        const type = TYPES[extname(file).toLowerCase()]
        if (!type || !file.startsWith(PHOTOS + sep) || !existsSync(file) || !statSync(file).isFile()) return next()
        res.setHeader('Content-Type', type)
        createReadStream(file).pipe(res)
      })
    },
    closeBundle() {
      if (!existsSync(PHOTOS)) return
      const dest = join(outDir, 'photos')
      mkdirSync(dest, { recursive: true })
      for (const f of readdirSync(PHOTOS)) {
        if (TYPES[extname(f).toLowerCase()]) cpSync(join(PHOTOS, f), join(dest, f))
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), missionPhotos()],
  // The app reads everything in ../data/out (layers.json, images, route, ...) as if it sat next to index.html
  publicDir: '../data/out',
  // Relative paths so the build works on any static host
  base: './',
})
