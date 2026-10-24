import { service } from '../features/services'
import { endpoints } from '../services/endpoints'
import type { WsEvent } from '../types'
import { useAsync } from './useAsync'
import { useSessionChannel } from './useSessionChannel'
const CHATTER = new Set(['rtc.signal', 'call.request', 'call.accept', 'call.decline', 'call.end', 'chat.message'])  // live-call traffic must not reload the whole page
/** Loads one session and refetches whenever the backend pushes an update for it. `onEvent` sees every event (the live call uses it). */
export function useSession(id: string, onEvent?: (e: WsEvent) => void) {
  const q = useAsync(() => service.getSession(id), [id])
  const ch = useSessionChannel(id ? endpoints.ws(id) : null, (e) => {
    if (e.session_id !== id) return
    onEvent?.(e)
    if (!CHATTER.has(e.event)) q.reload()
  })
  return { ...q, wsState: ch.state, send: ch.send }
}
