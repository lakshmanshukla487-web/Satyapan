import type { WsEvent } from '../../types'

export type CallState = 'idle' | 'asking' | 'connecting' | 'connected' | 'reconnecting' | 'ended' | 'failed'
/** The officer's own microphone in the call: on, muted by the officer, blocked/unavailable (the customer cannot hear the officer),
 *  or not used (customer side: the customer's microphone is the verification stream itself). */
export type MicState = 'on' | 'muted' | 'unavailable' | 'none'
type Send = (event: string, data?: Record<string, unknown>) => boolean
export interface CallHooks {
  send: Send
  iceServers: RTCIceServer[]
  onRemote: (s: MediaStream | null) => void
  onState: (s: CallState, detail?: string) => void
  onMic?: (s: MicState, detail?: string) => void
}

export const ANSWER_TIMEOUT_MS = 45_000   // the customer has this long to accept before the request is withdrawn
const CONNECT_TIMEOUT_MS = 30_000         // accepted, but no media path within this time: give up with a clear message
const DISCONNECT_GRACE_MS = 12_000        // a dropped path may recover by itself (network change) before we call it ended

export const newCallId = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`)
interface Signal { kind?: string; sdp?: string; candidate?: RTCIceCandidateInit | null; call_id?: string; reason?: string }

/** One officer <-> customer call over WebRTC. The server only relays the small signalling messages (it never sees the media).
 *  The officer always makes the offer: receive-only video plus the officer's microphone; the customer answers with the camera and
 *  microphone that already run for the verification (the call adds no new capture on the customer's side).
 *
 *  Robustness: every message carries this call's id and messages of any other call are ignored (no stale offer, answer or ICE
 *  candidate can reach a new connection); signalling is processed strictly in order (an ICE candidate never races the offer);
 *  remote tracks are collected into ONE stream (audio and video both reach the page); timeouts end a call nobody answers or
 *  that cannot connect, instead of leaving it "connecting" forever. */
export class LiveCall {
  private pc: RTCPeerConnection | null = null
  private queued: RTCIceCandidateInit[] = []
  private mic: MediaStream | null = null
  private remote: MediaStream | null = null
  private chain: Promise<void> = Promise.resolve()
  private closed = false
  private timers: number[] = []
  private disconnectTimer: number | undefined
  constructor(private role: 'officer' | 'customer', readonly callId: string, private h: CallHooks, private getLocal?: () => MediaStream | null) {}

  /** Officer: ask the customer. Withdrawn automatically if nobody answers. */
  request(): boolean {
    if (!this.h.send('call.request', { call_id: this.callId })) { this.close('failed', 'Not connected to the server, so the customer could not be asked. Try again in a moment.'); return false }
    this.h.onState('asking')
    this.after(ANSWER_TIMEOUT_MS, () => { if (!this.pc && !this.closed) { this.h.send('call.end', { call_id: this.callId, reason: 'no_answer' }); this.close('failed', 'The customer did not answer the call request.') } })
    return true
  }

  /** Customer: accept the officer's request (the verification camera and microphone are already on). */
  accept(): boolean {
    if (!this.getLocal?.()) { this.close('failed', 'Start your camera first, then accept the call.'); return false }
    if (!this.h.send('call.accept', { call_id: this.callId })) { this.close('failed', 'Not connected to the server. Please try again.'); return false }
    this.h.onState('connecting')
    this.armConnectTimeout()
    return true
  }

  /** True when the message belongs to this call (messages from older clients without an id are accepted). */
  owns(e: WsEvent): boolean {
    const id = (e.data as Signal | null)?.call_id
    return !id || id === this.callId
  }

  /** Feed every call/signal event of the session socket. Processed one after the other, in arrival order. */
  handle(e: WsEvent): Promise<void> {
    if (!this.owns(e)) return Promise.resolve()
    this.chain = this.chain.then(() => this.process(e)).catch((x) => this.close('failed', x instanceof Error ? x.message : 'Call setup failed.'))
    return this.chain
  }

  /** Officer: mute or unmute the officer's microphone (the connection stays up). */
  setMicMuted(muted: boolean): void {
    const tracks = this.mic?.getAudioTracks() ?? []
    if (!tracks.length) return
    tracks.forEach((t) => { t.enabled = !muted })
    this.h.onMic?.(muted ? 'muted' : 'on')
  }

  hangUp(reason = ''): void {
    if (this.closed) return
    this.h.send('call.end', { call_id: this.callId, reason })
    this.close('ended')
  }

  close(state: CallState = 'ended', detail?: string): void {
    if (this.closed) return
    this.closed = true
    this.timers.forEach((t) => window.clearTimeout(t)); this.timers = []
    window.clearTimeout(this.disconnectTimer)
    this.mic?.getTracks().forEach((t) => t.stop())  // only the officer's call microphone: the customer's verification stream is never stopped here
    this.mic = null
    const pc = this.pc
    this.pc = null; this.queued = []; this.remote = null
    if (pc) { pc.onicecandidate = null; pc.ontrack = null; pc.onconnectionstatechange = null; try { pc.close() } catch { /* already closed */ } }
    this.h.onRemote(null)
    this.h.onState(state, detail)
  }

  get isClosed() { return this.closed }

  /* ------------------------------------------------------------------------------------------------------------------ internals */
  private after(ms: number, fn: () => void) { this.timers.push(window.setTimeout(fn, ms)) }
  private armConnectTimeout() {
    this.after(CONNECT_TIMEOUT_MS, () => {
      if (this.closed || this.pc?.connectionState === 'connected') return
      this.h.send('call.end', { call_id: this.callId, reason: 'connect_timeout' })
      this.close('failed', 'The video connection could not be established. A firewall may be blocking direct connections; a TURN relay (TURN_URLS) is needed on such networks.')
    })
  }

  private async process(e: WsEvent): Promise<void> {
    if (this.closed) return
    const d = (e.data ?? {}) as Signal
    if (e.event === 'call.end' || e.event === 'call.decline') {
      this.close(e.event === 'call.decline' ? 'failed' : 'ended', e.event === 'call.decline' ? 'The customer declined the call.' : d.reason === 'no_answer' ? 'The call request was withdrawn.' : 'The other side ended the call.')
      return
    }
    if (e.event === 'call.accept' && this.role === 'officer' && !this.pc) { await this.offer(); return }
    if (e.event !== 'rtc.signal') return
    if (d.kind === 'offer' && this.role === 'customer' && d.sdp) {
      const local = this.getLocal?.()
      if (!local || !local.getTracks().some((t) => t.readyState === 'live')) {
        this.h.send('call.end', { call_id: this.callId, reason: 'no_camera' })
        this.close('failed', 'Your camera is not running, so the officer cannot see you. Start the camera and accept again.')
        return
      }
      const pc = this.make()
      await pc.setRemoteDescription({ type: 'offer', sdp: d.sdp })
      local.getTracks().filter((t) => t.readyState === 'live').forEach((t) => pc.addTrack(t, local))  // reuses the transceivers the offer created
      await pc.setLocalDescription(await pc.createAnswer())
      this.h.send('rtc.signal', { kind: 'answer', sdp: pc.localDescription?.sdp ?? '', call_id: this.callId })
      await this.flush()
    } else if (d.kind === 'answer' && this.role === 'officer' && d.sdp && this.pc && this.pc.signalingState === 'have-local-offer') {
      await this.pc.setRemoteDescription({ type: 'answer', sdp: d.sdp })
      await this.flush()
    } else if (d.kind === 'candidate' && d.candidate) {
      if (this.pc?.remoteDescription) await this.pc.addIceCandidate(d.candidate).catch(() => undefined)
      else this.queued.push(d.candidate)  // arrived before the description it belongs to: applied right after it
    }
  }

  /** Officer: the customer accepted, so build the connection and send the offer. */
  private async offer(): Promise<void> {
    this.h.onState('connecting')
    this.armConnectTimeout()
    const pc = this.make()
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false })
    } catch (x) {
      this.mic = null
      const name = x instanceof DOMException ? x.name : ''
      this.h.onMic?.('unavailable', name === 'NotAllowedError' ? 'Your microphone is blocked in the browser, so the customer cannot hear you. You can still see and hear the customer.'
        : 'No microphone was available, so the customer cannot hear you. You can still see and hear the customer.')
    }
    if (this.closed || this.pc !== pc) { this.mic?.getTracks().forEach((t) => t.stop()); return }
    if (this.mic) { this.mic.getAudioTracks().forEach((t) => pc.addTrack(t, this.mic as MediaStream)); this.h.onMic?.('on') }
    else pc.addTransceiver('audio', { direction: 'recvonly' })
    pc.addTransceiver('video', { direction: 'recvonly' })
    await pc.setLocalDescription(await pc.createOffer())
    this.h.send('rtc.signal', { kind: 'offer', sdp: pc.localDescription?.sdp ?? '', call_id: this.callId })
  }

  private make(): RTCPeerConnection {
    if (this.pc) { try { this.pc.close() } catch { /* ignore */ } }
    const pc = new RTCPeerConnection({ iceServers: this.h.iceServers })
    this.pc = pc
    pc.onicecandidate = (ev) => { if (this.pc === pc) this.h.send('rtc.signal', { kind: 'candidate', candidate: ev.candidate ? ev.candidate.toJSON() : null, call_id: this.callId }) }
    pc.ontrack = (ev) => {
      if (this.pc !== pc) return
      // Collect every remote track in one stream: a new MediaStream object per change so the page re-attaches it.
      const tracks = [...(this.remote?.getTracks() ?? []).filter((t) => t.id !== ev.track.id), ev.track]
      this.remote = new MediaStream(tracks)
      this.h.onRemote(this.remote)
      ev.track.onended = () => { if (this.pc === pc && this.remote) { this.remote = new MediaStream(this.remote.getTracks().filter((t) => t.readyState === 'live')); this.h.onRemote(this.remote) } }
    }
    pc.onconnectionstatechange = () => {
      if (this.pc !== pc) return
      const st = pc.connectionState
      if (st === 'connected') { window.clearTimeout(this.disconnectTimer); this.h.onState('connected') }
      else if (st === 'disconnected') {
        this.h.onState('reconnecting', 'The connection dropped; trying to recover...')
        window.clearTimeout(this.disconnectTimer)
        this.disconnectTimer = window.setTimeout(() => { if (this.pc === pc && pc.connectionState !== 'connected') { this.h.send('call.end', { call_id: this.callId, reason: 'lost' }); this.close('ended', 'The connection was lost.') } }, DISCONNECT_GRACE_MS)
      } else if (st === 'failed') { this.h.send('call.end', { call_id: this.callId, reason: 'failed' }); this.close('failed', 'The connection could not be established (a firewall may be blocking it; a TURN relay may be needed).') }
    }
    return pc
  }

  private async flush(): Promise<void> {
    const q = this.queued.splice(0)
    for (const c of q) await this.pc?.addIceCandidate(c).catch(() => undefined)
  }
}
