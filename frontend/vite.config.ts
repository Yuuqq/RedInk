import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env || {}
const apiProxyTarget = env.VITE_API_PROXY_TARGET || `http://localhost:${env.REDINK_PORT || '12398'}`

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true
      }
    }
  }
})
