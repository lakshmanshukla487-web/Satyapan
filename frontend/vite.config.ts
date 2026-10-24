import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// Optional LAN TLS certificate (run ../setup-https.sh to generate certs/lan.crt and certs/lan.key for your machine).
// Falls back to plain HTTP when the cert files are missing (localhost still works; LAN camera will not).
const certDir = path.resolve(__dirname, 'certs')
const hasCerts = fs.existsSync(path.join(certDir, 'lan.crt')) && fs.existsSync(path.join(certDir, 'lan.key'))

const BACKEND = 'http://127.0.0.1:8000'

// When the Django server is not running (or crashed while starting) Vite's proxy used to answer with a bare, empty HTTP 500,
// which looked like a backend bug (for example on "Register"). Answer with a JSON 503 that says what is wrong instead.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const onProxyError = (proxy: any) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  proxy.on('error', (err: Error, _req: unknown, res: any) => {
    if (!res || typeof res.writeHead !== 'function' || res.headersSent) return
    res.writeHead(503, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: { code: 'BACKEND_UNREACHABLE', message: 'Cannot reach the Satyapan server on port 8000. Start the backend (see the terminal running it for errors) and try again.', request_id: null } }))
    console.error('[vite proxy] backend unreachable:', err.message)
  })
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // HTTPS: required for getUserMedia() on non-localhost LAN origins.
    ...(hasCerts ? {
      https: {
        cert: fs.readFileSync(path.join(certDir, 'lan.crt')),
        key: fs.readFileSync(path.join(certDir, 'lan.key')),
      },
    } : {}),
    // Proxy: forward /api and /ws to the Django/Daphne backend so the browser
    // only talks to one origin (the Vite HTTPS server). This avoids mixed-content
    // blocks (HTTPS page → HTTP API) and keeps CORS simple.
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        xfwd: true, // adds X-Forwarded-For so the backend sees the customer's real address (IP / VPN check)
        configure: onProxyError,
      },
      '/ws': {
        target: BACKEND,
        ws: true,
        changeOrigin: true,
        xfwd: true,
        configure: onProxyError,
      },
    },
  },
})

