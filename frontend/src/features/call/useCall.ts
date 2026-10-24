import { useCallback, useEffect, useRef, useState } from 'react'
import { service } from '../services'
import type { WsEvent } from '../../types'
import { LiveCall, type CallState } from './liveCall'

export interface ChatLine { from: 'officer' | 'customer'; text: string; at: number }
type Send = (event: string, data?: Record<string, unknown>) => boolean

/** Call + chat state for one side. `onEvent` must be given every socket event; `send` is the socket's send. */
export function useCall(role: 'officer' | 'customer', send: Send, getLocal?: () => MediaStream | null) {
  const [state, setState] = useState<CallState>('idle')
  const [detail, setDetail] = useState('')
  const [remote, setRemote] = useState<MediaStream | null>(null)
  const [incoming, setIncoming] = useState(false)
  const [chat, setChat] = useState<ChatLine[]>([])
  const [enabled, setEnabled] = useState(true)
  const call = useRef<LiveCall | null>(null)
  const ice = useRef<RTCIceServer[]>([{ urls: 'stun:stun.l.google.com:19302' }])
  const sendRef = useRef(send); sendRef.current = send
  const localRef = useRef(getLocal); localRef.current = getLocal

  useEffect(() => {
    service.getRtcConfig().then((c) => { setEnabled(c.enabled); if (c.iceServers.length) ice.current = c.iceServers as RTCIceServer[] }).catch(() => undefined)
    return () => { call.current?.close('ended'); call.current = null }
  }, [])

  const make = useCallback(() => {
    call.current?.close('ended')
    call.current = new LiveCall(role, {
      send: (e, d) => sendRef.current(e, d), iceServers: ice.current, onRemote: setRemote,
      onState: (s, d) => { setState(s); setDetail(d ?? ''); if (s === 'ended' || s === 'failed') { setRemote(null); setIncoming(false) } },
    }, () => localRef.current?.() ?? null)
    return call.current
  }, [role])

  /** Officer: ask the customer to start a live call. */
  const request = useCallback(() => { make(); setState('asking'); setDetail(''); if (!sendRef.current('call.request')) { setState('failed'); setDetail('Not connected to the server.') } }, [make])
  /** Customer: accept the officer's request (their camera and microphone are already on). */
  const accept = useCallback(() => { make(); setIncoming(false); setState('connecting'); sendRef.current('call.accept') }, [make])
  const decline = useCallback(() => { setIncoming(false); sendRef.current('call.decline') }, [])
  const hangUp = useCallback(() => { if (call.current) call.current.hangUp(); else sendRef.current('call.end'); call.current = null }, [])
  const sendChat = useCallback((text: string) => {
    const t = text.trim().slice(0, 500)
    if (!t || !sendRef.current('chat.message', { text: t })) return false
    setChat((c) => [...c.slice(-99), { from: role, text: t, at: Date.now() }])
    return true
  }, [role])

  const onEvent = useCallback((e: WsEvent) => {
    const d = (e.data ?? {}) as { text?: string; from?: string }
    if (e.event === 'chat.message' && d.text && (d.from === 'officer' || d.from === 'customer')) setChat((c) => [...c.slice(-99), { from: d.from as ChatLine['from'], text: d.text as string, at: Date.now() }])
    else if (e.event === 'call.request' && role === 'customer') { setIncoming(true); setDetail('') }
    else if (e.event === 'call.accept' || e.event === 'call.end' || e.event === 'call.decline' || e.event === 'rtc.signal') void call.current?.handle(e)
    if ((e.event === 'call.end' || e.event === 'call.decline') && !call.current) { setIncoming(false); setState(e.event === 'call.decline' ? 'failed' : 'ended'); if (e.event === 'call.decline') setDetail('The customer declined the call.') }
  }, [role])

  return { state, detail, remote, incoming, chat, enabled, request, accept, decline, hangUp, sendChat, onEvent }
}
