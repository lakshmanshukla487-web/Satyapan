/** Holds the session token. sessionStorage: survives a refresh, is cleared when the tab closes. */
const KEY = 'satyapan.token'
let memory: string | null = null
const listeners = new Set<() => void>()

export function getToken(): string | null {
  try { return sessionStorage.getItem(KEY) ?? memory } catch { return memory }
}
export function setToken(token: string | null): void {
  memory = token
  try { if (token) sessionStorage.setItem(KEY, token); else sessionStorage.removeItem(KEY) } catch { /* storage blocked: memory only */ }
}
/** Called by the API client when the server rejects the token (expired or revoked). */
export function onUnauthorized(fn: () => void): () => void { listeners.add(fn); return () => { listeners.delete(fn) } }
export function emitUnauthorized(): void { listeners.forEach((f) => f()) }
