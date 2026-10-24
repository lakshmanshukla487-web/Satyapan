// When VITE_API_BASE_URL is empty the proxy mode is active: Vite forwards /api
// and /ws to the Django backend, so the browser only talks to the Vite origin.
// This avoids mixed-content blocks (HTTPS page → HTTP API) and lets the app
// work at any hostname without reconfiguration.
const apiBase = import.meta.env.VITE_API_BASE_URL ?? ''

// Derive the WebSocket base URL from the page's own origin when the env var is
// absent, so it automatically upgrades to wss:// on HTTPS pages.
function deriveWsBase(): string {
  const env = import.meta.env.VITE_WS_BASE_URL
  if (env) return env
  if (typeof window === 'undefined') return ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export const env = {
  apiBaseUrl: apiBase,
  get wsBaseUrl() { return deriveWsBase() },
  useMocks: (import.meta.env.VITE_USE_MOCKS ?? 'true') !== 'false',
}
