import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = process.env.PHOTO_BACKEND ?? 'http://127.0.0.1:7860'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The backend checks Host/Origin; changeOrigin makes them match its own address.
      '/api': { target: backend, changeOrigin: true, ws: true },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: 'jsdom',
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
})
