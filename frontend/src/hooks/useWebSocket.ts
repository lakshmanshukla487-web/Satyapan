import { useEffect, useRef, useState } from 'react'
import { env } from '../config/env'
import { SessionSocket } from '../services/websocketClient'
import type { WsEvent, WsState } from '../types'
/** Connects only against the real backend; stays 'idle' in mock mode. Closes on unmount. */
export function useWebSocket(path: string | null, onEvent: (e: WsEvent) => void): WsState {
  const [state, setState] = useState<WsState>('idle')
  const cb = useRef(onEvent)
  cb.current = onEvent
  useEffect(() => {
    if (!path || env.useMocks) return
    const s = new SessionSocket(path, { onEvent: (e) => cb.current(e), onState: setState })
    s.connect()
    return () => s.close()
  }, [path])
  return state
}
