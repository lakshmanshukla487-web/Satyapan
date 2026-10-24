import { env } from '../config/env'
import { backoffMs } from './apiClient'
import { getToken } from './tokenStore'
import type { WsEvent, WsState } from '../types'
type Handlers = { onEvent: (e: WsEvent) => void; onState: (s: WsState) => void }

/** Close codes the server uses for "this will never work": not signed in, wrong role / origin, unknown session. */
const TERMINAL_CODES = new Set([4401, 4403, 4404])
const FAST_RETRIES = 5
const SLOW_RETRY_MS = 30_000

/** Reconnecting WebSocket wrapper. Quick exponential backoff (with jitter) for the first attempts, then a slow retry every ~30 s
 *  for as long as the page is open (the page polls in the meantime). A refusal the server marks as final is not retried.
 *  Call close() on unmount: it stops every timer, so a remount never leaves a second socket or loop behind. */
export class SessionSocket {
  private ws: WebSocket | null = null
  private retries = 0
  private timer: number | undefined
  private stopped = false
  constructor(private path: string, private h: Handlers) {}
  connect() {
    this.stopped = false
    window.clearTimeout(this.timer)
    const token = getToken()
    if (!token) return this.h.onState('closed')  // not signed in
    this.h.onState(this.retries ? 'reconnecting' : 'connecting')
    // Browsers cannot set headers on a WebSocket, so the token rides in the subprotocol list (never in the URL or logs).
    let ws: WebSocket
    try { ws = new WebSocket(env.wsBaseUrl + this.path, ['satyapan.v1', token]) } catch { return this.schedule() }
    this.ws = ws
    ws.onopen = () => { if (this.ws !== ws) return; this.retries = 0; this.h.onState('open') }
    ws.onmessage = (m) => { if (this.ws !== ws) return; try { this.h.onEvent(JSON.parse(String(m.data)) as WsEvent) } catch { /* ignore malformed */ } }
    ws.onclose = (ev) => {
      if (this.ws !== ws) return  // an old socket closing after a reconnect must not touch the new one
      this.ws = null
      if (this.stopped || TERMINAL_CODES.has(ev.code)) return this.h.onState('closed')
      this.schedule()
    }
  }
  private schedule() {
    if (this.stopped) return
    this.h.onState('reconnecting')
    const wait = this.retries < FAST_RETRIES ? 500 + backoffMs(this.retries, 1000, 15000) : SLOW_RETRY_MS + backoffMs(0, 5000, 5000)
    window.clearTimeout(this.timer)
    this.timer = window.setTimeout(() => { this.retries++; this.connect() }, wait)
  }
  /** Sends one JSON message (live-call signalling and chat). Returns false if the socket is not open. */
  send(event: string, data: Record<string, unknown> = {}): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ event, data }))
    return true
  }
  close() {
    this.stopped = true
    window.clearTimeout(this.timer)
    const ws = this.ws
    this.ws = null
    ws?.close()
    this.h.onState('closed')
  }
}
