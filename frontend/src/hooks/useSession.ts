import { useCallback, useEffect, useRef, useState } from 'react'
import { applyLiveEvent } from '../features/realService'
import { service } from '../features/services'
import { env } from '../config/env'
import { endpoints } from '../services/endpoints'
import type { SessionPart, VerificationSession, WsEvent, WsState } from '../types'
import { useSessionChannel } from './useSessionChannel'

const CHATTER = new Set(['rtc.signal', 'call.request', 'call.accept', 'call.decline', 'call.end', 'chat.message'])  // live-call traffic never reloads data
const NOOP = new Set(['detector.started', 'detector.completed', 'detector.unavailable'])  // the matching signal.updated carries the result
const PARTS_FOR: Record<string, SessionPart[]> = {
  'challenge.pending': ['challenges'], 'challenge.approved': ['challenges'], 'challenge.issued': ['challenges'], 'challenge.result': ['challenges'], 'challenge.released': ['challenges'],
  'document.uploaded': ['documents'], 'document.removed': ['documents'], 'documents.checked': ['documents', 'analysis'],
  'session.status': ['core', 'challenges'], 'session.approved': ['core'], 'session.rejected': ['core'], 'session.requested': ['core'], 'session.terminated': ['core', 'challenges', 'analysis'],
  'biometric.updated': ['analysis'], 'error': [],
}
const DEBOUNCE_MS = 400      // events of one upload or one approval arrive together: fetch once
const MIN_GAP_MS = 1500      // at most one refresh round every 1.5 s, however many events arrive
const EVENTS_EVERY_MS = 10_000  // the activity list is refreshed at most every 10 s
const FALLBACK_POLL_MS = 10_000 // while the socket is down: a bounded full refresh every 10 s (and only one loop)

/** One session for the officer's live workspace, kept current WITHOUT request storms:
 *  - events that carry the new state (risk.updated, signal.updated) are applied directly, no request at all;
 *  - other events only refetch the part they concern (challenges, documents, ...), coalesced (debounce + minimum gap) and with
 *    only one refresh in flight at a time;
 *  - while the socket is down, one bounded polling loop takes over; it stops as soon as the socket is back.
 *  `onEvent` sees every event (the live call uses it). */
export function useSession(id: string, onEvent?: (e: WsEvent) => void) {
  const [data, setData] = useState<VerificationSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const dataRef = useRef<VerificationSession | null>(null)
  const pending = useRef(new Set<SessionPart>())
  const timer = useRef<number | undefined>(undefined)
  const busy = useRef(false)
  const lastRun = useRef(0)
  const lastEvents = useRef(0)
  const gen = useRef(0)
  const cb = useRef(onEvent)
  cb.current = onEvent
  dataRef.current = data

  const run = useCallback(async () => {
    const g = gen.current
    const cur = dataRef.current
    if (busy.current || !cur) return
    const parts = [...pending.current]
    pending.current.clear()
    if (!parts.length) return
    busy.current = true
    lastRun.current = Date.now()
    if (parts.includes('events')) lastEvents.current = Date.now()
    try {
      const next = await service.refreshSession(id, parts, cur)
      if (g !== gen.current) return
      // Merge onto the newest state: live events may have been applied while the request was running.
      setData((prev) => (prev ? { ...prev, ...Object.fromEntries(Object.entries(next).filter(([k]) => partKeys(parts).has(k))) } : next))
      setError(null)
    } catch (e) {
      if (g !== gen.current) return
      parts.forEach((p) => pending.current.add(p))  // try these again on the next round
      setError(e instanceof Error ? e.message : 'Could not refresh the session.')
    } finally {
      if (g === gen.current) {
        busy.current = false
        if (pending.current.size) scheduleRef.current()
      }
    }
  }, [id])

  const schedule = useCallback(() => {
    if (timer.current !== undefined) return  // a round is already planned: the new parts ride along (no starvation under constant events)
    const wait = Math.max(DEBOUNCE_MS, MIN_GAP_MS - (Date.now() - lastRun.current))
    timer.current = window.setTimeout(() => { timer.current = undefined; void run() }, wait)
  }, [run])
  const scheduleRef = useRef(schedule)
  scheduleRef.current = schedule

  const request = useCallback((parts: SessionPart[]) => {
    if (!parts.length) return
    parts.forEach((p) => pending.current.add(p))
    if (!pending.current.has('events') && Date.now() - lastEvents.current > EVENTS_EVERY_MS) pending.current.add('events')
    schedule()
  }, [schedule])

  const reload = useCallback(() => request(['core', 'analysis', 'challenges', 'events', 'documents']), [request])

  // first load
  useEffect(() => {
    const g = ++gen.current
    setLoading(true); setData(null); setError(null)
    pending.current.clear(); busy.current = false
    service.getSession(id)
      .then((s) => { if (g === gen.current) { setData(s); lastEvents.current = Date.now() } })
      .catch((e: unknown) => { if (g === gen.current) setError(e instanceof Error ? e.message : 'Could not load the session.') })
      .finally(() => { if (g === gen.current) setLoading(false) })
    return () => { gen.current++; window.clearTimeout(timer.current); timer.current = undefined }
  }, [id])

  const onSocket = useCallback((e: WsEvent) => {
    if (e.session_id !== id) return  // never act on another session's event
    cb.current?.(e)
    if (CHATTER.has(e.event) || NOOP.has(e.event)) return
    const cur = dataRef.current
    if (cur) {
      const applied = applyLiveEvent(cur, e)
      if (applied) { setData(applied); return }
    }
    request(PARTS_FOR[e.event] ?? ['core', 'analysis'])
  }, [id, request])
  const ch = useSessionChannel(id ? endpoints.ws(id) : null, onSocket)

  // bounded polling fallback while the socket is not open (one interval, recreated only when the state changes)
  const wsOpen = ch.state === 'open'
  useEffect(() => {
    if (env.useMocks || wsOpen || !id) return
    const t = window.setInterval(() => request(['core', 'analysis', 'challenges', 'documents']), FALLBACK_POLL_MS)
    return () => window.clearInterval(t)
  }, [wsOpen, id, request])
  // after a reconnect: one catch-up refresh for whatever happened while the socket was down
  const prevState = useRef<WsState>('idle')
  useEffect(() => {
    if (ch.state === 'open' && prevState.current === 'reconnecting') reload()
    prevState.current = ch.state
  }, [ch.state, reload])

  return { data, error, loading, reload, refresh: request, wsState: ch.state, send: ch.send }
}

function partKeys(parts: SessionPart[]): Set<string> {
  const keys: Record<SessionPart, string[]> = {
    core: ['customer', 'startedAt', 'status', 'approval', 'autoApprove', 'backendStatus', 'terminationReason'],
    analysis: ['tier', 'recommendation', 'reasons', 'reasonDetails', 'headline', 'nextSteps', 'families', 'coverage', 'overallExplain', 'missingForGreen', 'signals'],
    challenges: ['challenges'], events: ['events'], documents: ['documents'],
  }
  return new Set(parts.flatMap((p) => keys[p]))
}
