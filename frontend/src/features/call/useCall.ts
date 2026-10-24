import { useCallback, useEffect, useRef, useState } from 'react'
import { service } from '../services'
import type { WsEvent } from '../../types'
import { ANSWER_TIMEOUT_MS, LiveCall, newCallId, type CallState, type MicState } from './liveCall'

export interface ChatLine { from: 'officer' | 'customer'; text: string; at: number }
type Send = (event: string, data?: Record<string, unknown>) => boolean
const CALL_EVENTS = new Set(['call.accept', 'call.end', 'call.decline', 'rtc.signal'])

/** Call + chat state for one side. `onEvent` must be given every socket event of THIS session; `send` is that socket's send.
 *  Customer: `getLocal` returns the verification stream (camera + microphone), which the call shares; it never starts a capture. */
export function useCall(role: 'officer' | 'customer', send: Send, getLocal?: () => MediaStream | null) {
  const [state, setState] = useState<CallState>('idle')
  const [detail, setDetail] = useState('')
  const [remote, setRemote] = useState<MediaStream | null>(null)
  const [incoming, setIncoming] = useState(false)
  const [chat, setChat] = useState<ChatLine[]>([])
  const [enabled, setEnabled] = useState(true)
  const [relayConfigured, setRelayConfigured] = useState(false)
  const [mic, setMic] = useState<MicState>('none')
  const [micDetail, setMicDetail] = useState('')
  const call = useRef<LiveCall | null>(null)
  const incomingId = useRef<string | null>(null)
  const incomingTimer = useRef<number | undefined>(undefined)
  const ice = useRef<RTCIceServer[]>([{ urls: 'stun:stun.l.google.com:19302' }])
  const sendRef = useRef(send); sendRef.current = send
  const localRef = useRef(getLocal); localRef.current = getLocal

  useEffect(() => {
    let alive = true
    service.getRtcConfig().then((c) => { if (!alive) return; setEnabled(c.enabled); setRelayConfigured(c.relayConfigured); if (c.iceServers.length) ice.current = c.iceServers as RTCIceServer[] }).catch(() => undefined)
    return () => {
      alive = false
      window.clearTimeout(incomingTimer.current)
      call.current?.hangUp('left')  // leaving the page ends the call for the other side too (not just locally)
      call.current = null
    }
  }, [])

  // Closing or reloading the tab does not run React clean-ups: tell the other side the call is over (best effort).
  useEffect(() => {
    const bye = () => call.current?.hangUp('left')
    window.addEventListener('pagehide', bye)
    return () => window.removeEventListener('pagehide', bye)
  }, [])

  const make = useCallback((id: string) => {
    call.current?.close('ended')
    setMic('none'); setMicDetail('')
    const c: LiveCall = new LiveCall(role, id, {
      send: (e, d) => sendRef.current(e, d), iceServers: ice.current,
      onRemote: (s) => { if (call.current === c) setRemote(s) },
      onState: (s, d) => {
        if (call.current !== c) return
        setState(s); setDetail(d ?? '')
        if (s === 'ended' || s === 'failed') { setRemote(null); setIncoming(false); call.current = null; setMic('none') }
      },
      onMic: (m, d) => { if (call.current === c) { setMic(m); setMicDetail(d ?? '') } },
    }, () => localRef.current?.() ?? null)
    call.current = c
    return c
  }, [role])

  /** Officer: ask the customer to start a live call. */
  const request = useCallback(() => { setDetail(''); make(newCallId()).request() }, [make])
  /** Customer: accept the officer's request. */
  const accept = useCallback(() => {
    const id = incomingId.current
    window.clearTimeout(incomingTimer.current)
    setIncoming(false)
    if (!id) return
    make(id).accept()
  }, [make])
  const decline = useCallback(() => {
    window.clearTimeout(incomingTimer.current)
    setIncoming(false)
    sendRef.current('call.decline', incomingId.current ? { call_id: incomingId.current } : {})
    incomingId.current = null
  }, [])
  const hangUp = useCallback(() => {
    if (call.current) call.current.hangUp()
    else { setState((s) => (s === 'idle' ? s : 'ended')); setIncoming(false) }
  }, [])
  const setMicMuted = useCallback((muted: boolean) => call.current?.setMicMuted(muted), [])
  const sendChat = useCallback((text: string) => {
    const t = text.trim().slice(0, 500)
    if (!t || !sendRef.current('chat.message', { text: t })) return false
    setChat((c) => [...c.slice(-99), { from: role, text: t, at: Date.now() }])
    return true
  }, [role])

  const onEvent = useCallback((e: WsEvent) => {
    const d = (e.data ?? {}) as { text?: string; from?: string; call_id?: string }
    if (e.event === 'chat.message') {
      if (d.text && (d.from === 'officer' || d.from === 'customer')) setChat((c) => [...c.slice(-99), { from: d.from as ChatLine['from'], text: d.text as string, at: Date.now() }])
      return
    }
    if (e.event === 'call.request' && role === 'customer') {
      // A new request replaces whatever was there (e.g. the officer reloaded the page and asks again).
      if (call.current && d.call_id !== call.current.callId) { call.current.close('ended'); call.current = null }
      incomingId.current = d.call_id ?? newCallId()
      setIncoming(true); setDetail('')
      window.clearTimeout(incomingTimer.current)
      incomingTimer.current = window.setTimeout(() => { setIncoming(false); incomingId.current = null }, ANSWER_TIMEOUT_MS)
      return
    }
    if (!CALL_EVENTS.has(e.event)) return
    if (call.current) { void call.current.handle(e); return }  // the call ignores messages of other call ids
    if (role === 'customer' && (e.event === 'call.end' || e.event === 'call.decline') && (!d.call_id || d.call_id === incomingId.current)) {
      window.clearTimeout(incomingTimer.current); setIncoming(false); incomingId.current = null  // the officer withdrew the request
    }
  }, [role])

  return { state, detail, remote, incoming, chat, enabled, relayConfigured, mic, micDetail, request, accept, decline, hangUp, setMicMuted, sendChat, onEvent }
}
export type CallApi = ReturnType<typeof useCall>
