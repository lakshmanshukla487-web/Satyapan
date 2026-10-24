import { useEffect, useState } from 'react'
import { env } from '../config/env'
import type { WsState } from '../types'
export function useConnectionStatus(ws: WsState, fetchFailed: boolean) {
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true), down = () => setOnline(false)
    window.addEventListener('online', up); window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  if (!online) return { label: 'Offline', tone: 'red' as const }
  if (fetchFailed) return { label: 'Disconnected', tone: 'red' as const }
  if (env.useMocks) return { label: 'Mock data (simulated)', tone: 'cyan' as const }
  if (ws === 'open') return { label: 'Live', tone: 'green' as const }
  if (ws === 'connecting' || ws === 'reconnecting') return { label: 'Reconnecting', tone: 'amber' as const }
  return { label: 'API connected', tone: 'green' as const }
}
