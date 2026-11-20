import react from '@vitejs/plugin-react'

declare const process: { env: Record<string, string | undefined> }
import { defineConfig } from 'vite'

export default defineConfig({
  // '/fittrace/' for the GitHub Pages build; '/' everywhere else.
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.FITTRACE_API_URL ?? 'http://localhost:8000', changeOrigin: true } },
  },
  build: {
    chunkSizeWarningLimit: 4000,
    rollupOptions: { output: { manualChunks: (id) => (id.includes('plotly') ? 'plotly' : undefined) } },
  },
})
