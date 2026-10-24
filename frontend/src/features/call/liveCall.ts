import type { WsEvent } from '../../types'

export type CallState = 'idle' | 'asking' | 'connecting' | 'connected' | 'ended' | 'failed'
type Send = (event: string, data?: Record<string, unknown>) => boolean
interface Hooks { send: Send; iceServers: RTCIceServer[]; onRemote: (s: MediaStream) => void; onState: (s: CallState, detail?: string) => void }

/** One officer <-> customer call over WebRTC. The server only relays the small signalling messages (it never sees the video).
 *  The officer always makes the offer: the customer's camera and microphone are added to the answer, and the officer adds only a
 *  microphone (so the officer can talk, and the customer can hear but not see the officer's screen). */
export class LiveCall {
  private pc: RTCPeerConnection | null = null
  private queued: RTCIceCandidateInit[] = []
  private mic: MediaStream | null = null
  constructor(private role: 'officer' | 'customer', private h: Hooks, private getLocal?: () => MediaStream | null) {}

  /** Officer: the customer accepted, so build the connection and send the offer. */
  async offer(): Promise<void> {
    this.h.onState('connecting')
    const pc = this.make()
    try { this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false }) } catch { this.mic = null }
    if (this.mic) this.mic.getAudioTracks().forEach((t) => pc.addTrack(t, this.mic as MediaStream))
    else pc.addTransceiver('audio', { direction: 'recvonly' })
    pc.addTransceiver('video', { direction: 'recvonly' })
    await pc.setLocalDescription(await pc.createOffer())
    this.h.send('rtc.signal', { kind: 'offer', sdp: pc.localDescription?.sdp ?? '' })
  }

  /** Feed every call/signal event that arrives on the socket. */
  async handle(e: WsEvent): Promise<void> {
    const d = (e.data ?? {}) as { kind?: string; sdp?: string; candidate?: RTCIceCandidateInit | null }
    if (e.event === 'call.end' || e.event === 'call.decline') { this.close(e.event === 'call.decline' ? 'failed' : 'ended', e.event === 'call.decline' ? 'The other side declined.' : undefined); return }
    if (e.event === 'call.accept' && this.role === 'officer') { await this.offer().catch((x) => this.close('failed', String(x))); return }
    if (e.event !== 'rtc.signal') return
    try {
      if (d.kind === 'offer' && this.role === 'customer' && d.sdp) {
        this.h.onState('connecting')
        const pc = this.make()
        await pc.setRemoteDescription({ type: 'offer', sdp: d.sdp })
        const local = this.getLocal?.()
        local?.getTracks().forEach((t) => pc.addTrack(t, local)) // reuses the transceivers the offer created
        await pc.setLocalDescription(await pc.createAnswer())
        this.h.send('rtc.signal', { kind: 'answer', sdp: pc.localDescription?.sdp ?? '' })
        await this.flush()
      } else if (d.kind === 'answer' && this.role === 'officer' && d.sdp && this.pc) {
        await this.pc.setRemoteDescription({ type: 'answer', sdp: d.sdp })
        await this.flush()
      } else if (d.kind === 'candidate') {
        if (d.candidate && this.pc?.remoteDescription) await this.pc.addIceCandidate(d.candidate).catch(() => undefined)
        else if (d.candidate) this.queued.push(d.candidate)
      }
    } catch (x) { this.close('failed', x instanceof Error ? x.message : 'Call setup failed.') }
  }

  hangUp(): void { this.h.send('call.end'); this.close('ended') }

  private make(): RTCPeerConnection {
    this.pc?.close()
    const pc = new RTCPeerConnection({ iceServers: this.h.iceServers })
    this.pc = pc
    pc.onicecandidate = (e) => { this.h.send('rtc.signal', { kind: 'candidate', candidate: e.candidate ? e.candidate.toJSON() : null }) }
    pc.ontrack = (e) => this.h.onRemote(e.streams[0] ?? new MediaStream([e.track]))
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') this.h.onState('connected')
      else if (pc.connectionState === 'failed') this.close('failed', 'The connection could not be established (a firewall may be blocking it).')
      else if (pc.connectionState === 'closed' && this.pc === pc) this.h.onState('ended')
    }
    return pc
  }
  private async flush(): Promise<void> {
    const q = this.queued.splice(0)
    for (const c of q) await this.pc?.addIceCandidate(c).catch(() => undefined)
  }
  close(state: CallState = 'ended', detail?: string): void {
    this.mic?.getTracks().forEach((t) => t.stop()); this.mic = null
    const pc = this.pc; this.pc = null; this.queued = []
    try { pc?.close() } catch { /* already closed */ }
    this.h.onState(state, detail)
  }
}
