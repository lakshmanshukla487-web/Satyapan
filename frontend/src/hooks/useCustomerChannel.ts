import { useCallback, useEffect, useRef, useState } from 'react'
import { env } from '../config/env'
import { endpoints } from '../services/endpoints'
import { SessionSocket } from '../services/websocketClient'
import type { WsEvent, WsState } from '../types'
/** The customer's own channel: approval result, released challenges, live-call signalling, chat and the neutral end-of-session
 *  message. Returns the socket state and a `send` for call/chat messages. Real backend only. */
 
export function useCustomerChannel(sessionId: string | null, onEvent: (e: WsEvent) => void): { state: WsState; send: (event: string, data?: Record<string, unknown>) => boolean } {
  const cb = useRef(onEvent)
  cb.current = onEvent
  const sock = useRef<SessionSocket | null>(null)
  const [state, setState] = useState<WsState>('idle')
  useEffect(() => {
    if (!sessionId || env.useMocks) return
    const s = new SessionSocket(endpoints.wsCustomer(sessionId), { onEvent: (e) => cb.current(e), onState: setState })
    sock.current = s
    s.connect()
    return () => { s.close(); sock.current = null }
  }, [sessionId])
  const send = useCallback((event: string, data: Record<string, unknown> = {}) => sock.current?.send(event, data) ?? false, [])
  return { state, send }
}
