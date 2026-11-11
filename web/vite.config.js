import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The app reads everything in ../data/out (layers.json, images, route, ...) as if it sat next to index.html
  publicDir: '../data/out',
  // Relative paths so the build works on any static host
  base: './',
})
