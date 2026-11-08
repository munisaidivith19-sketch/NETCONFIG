import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the browser talks only to Vite (same origin); Vite forwards /api to the backend.
// changeOrigin rewrites the Host header to 127.0.0.1:8000 so the backend's Host allowlist accepts it.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
  },
})
