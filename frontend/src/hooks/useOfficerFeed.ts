import { useEffect, useRef } from 'react'
import { env } from '../config/env'
import { endpoints } from '../services/endpoints'
import { SessionSocket } from '../services/websocketClient'
import type { WsEvent, WsState } from '../types'
import { useState } from 'react'
/** Officer-wide feed: new sessions, pending approvals, terminations, document checks. Real backend only. */
export function useOfficerFeed(onEvent: (e: WsEvent) => void): WsState {
  const [state, setState] = useState<WsState>('idle')
  const cb = useRef(onEvent)
  cb.current = onEvent
  useEffect(() => {
    if (env.useMocks) return
    const s = new SessionSocket(endpoints.wsFeed, { onEvent: (e) => cb.current(e), onState: setState })
    s.connect()
    return () => s.close()
  }, [])
  return state
}
