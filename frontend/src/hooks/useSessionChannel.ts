import { useCallback, useEffect, useRef, useState } from 'react'
import { env } from '../config/env'
import { SessionSocket } from '../services/websocketClient'
import type { WsEvent, WsState } from '../types'
/** An officer's socket for one session (risk events, challenges, live call, chat) with a `send`. Closes on unmount. */
export function useSessionChannel(path: string | null, onEvent: (e: WsEvent) => void): { state: WsState; send: (event: string, data?: Record<string, unknown>) => boolean } {
  const cb = useRef(onEvent)
  cb.current = onEvent
  const sock = useRef<SessionSocket | null>(null)
  const [state, setState] = useState<WsState>('idle')
  useEffect(() => {
    if (!path || env.useMocks) return
    const s = new SessionSocket(path, { onEvent: (e) => cb.current(e), onState: setState })
    sock.current = s
    s.connect()
    return () => { s.close(); sock.current = null }
  }, [path])
  const send = useCallback((event: string, data: Record<string, unknown> = {}) => sock.current?.send(event, data) ?? false, [])
  return { state, send }
}
