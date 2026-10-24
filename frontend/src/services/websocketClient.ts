import { env } from '../config/env'
import { getToken } from './tokenStore'
import type { WsEvent, WsState } from '../types'
type Handlers = { onEvent: (e: WsEvent) => void; onState: (s: WsState) => void }
/** Reconnecting WebSocket wrapper with exponential backoff. Call close() on unmount. */
export class SessionSocket {
  private ws: WebSocket | null = null
  private retries = 0
  private timer: number | undefined
  private stopped = false
  constructor(private path: string, private h: Handlers) {}
  connect() {
    this.stopped = false
    const token = getToken()
    if (!token) return this.h.onState('closed')  // not signed in
    this.h.onState(this.retries ? 'reconnecting' : 'connecting')
    // Browsers cannot set headers on a WebSocket, so the token rides in the subprotocol list (never in the URL or logs).
    const ws = new WebSocket(env.wsBaseUrl + this.path, ['satyapan.v1', token])
    this.ws = ws
    ws.onopen = () => { this.retries = 0; this.h.onState('open') }
    ws.onmessage = (m) => { try { this.h.onEvent(JSON.parse(String(m.data)) as WsEvent) } catch { /* ignore malformed */ } }
    ws.onclose = () => {
      if (this.stopped || this.retries >= 5) return this.h.onState('closed')
      this.h.onState('reconnecting')
      this.timer = window.setTimeout(() => { this.retries++; this.connect() }, Math.min(1000 * 2 ** this.retries, 15000))
    }
  }
  /** Sends one JSON message (live-call signalling and chat). Returns false if the socket is not open. */
  send(event: string, data: Record<string, unknown> = {}): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ event, data }))
    return true
  }
  close() { this.stopped = true; window.clearTimeout(this.timer); this.ws?.close(); this.h.onState('closed') }
}
