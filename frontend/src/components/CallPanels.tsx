import { useEffect, useRef, useState } from 'react'
import { Mic, MicOff, PhoneCall, PhoneOff, Send, Video, VideoOff, Volume2, VolumeX } from 'lucide-react'
import type { CallApi, ChatLine } from '../features/call/useCall'
import type { CallState } from '../features/call/liveCall'
import { Card, Pill, Spinner, btnDanger, btnGhost, btnPrimary, inputCls } from './ui'

type Call = Pick<CallApi, 'state' | 'detail' | 'remote' | 'incoming' | 'chat' | 'enabled' | 'request' | 'accept' | 'decline' | 'hangUp' | 'sendChat'> & Partial<Pick<CallApi, 'mic' | 'micDetail' | 'setMicMuted' | 'relayConfigured'>>

const STATE_TEXT: Record<CallState, string> = { idle: 'Not in a call', asking: 'Waiting for the customer to accept', connecting: 'Connecting', connected: 'Connected', reconnecting: 'Connection unstable', ended: 'Call ended', failed: 'Not connected' }
const STATE_TONE: Record<CallState, 'green' | 'amber' | 'slate' | 'red'> = { idle: 'slate', asking: 'amber', connecting: 'amber', connected: 'green', reconnecting: 'amber', ended: 'slate', failed: 'red' }
const active = (s: CallState) => s === 'asking' || s === 'connecting' || s === 'connected' || s === 'reconnecting'

/** Plays a remote stream's audio through an <audio> element and reports when the browser blocked autoplay, so the page can show
 *  an explicit "click to hear" control instead of failing silently. A WebRTC connection alone never guarantees audible sound. */
function useRemoteAudio(stream: MediaStream | null) {
  const ref = useRef<HTMLAudioElement | null>(null)
  const [blocked, setBlocked] = useState(false)
  const [muted, setMuted] = useState(false)
  const hasAudio = Boolean(stream?.getAudioTracks().length)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.srcObject = stream
    if (!stream || !hasAudio) { setBlocked(false); return }
    el.play().then(() => setBlocked(false)).catch((e: unknown) => setBlocked(e instanceof DOMException && e.name === 'NotAllowedError'))
  }, [stream, hasAudio])
  useEffect(() => { if (ref.current) ref.current.muted = muted }, [muted])
  const unblock = () => { const el = ref.current; if (el) void el.play().then(() => setBlocked(false)).catch(() => setBlocked(true)) }
  return { ref, blocked, muted, setMuted, hasAudio, unblock }
}

/** Live input level of a stream (0..1), from the Web Audio API. Shows the officer that sound is really arriving. */
function useLevel(stream: MediaStream | null, on: boolean) {
  const [level, setLevel] = useState(0)
  useEffect(() => {
    if (!stream || !on || !stream.getAudioTracks().length || typeof AudioContext === 'undefined') { setLevel(0); return }
    let ctx: AudioContext | null = null, raf = 0, stopped = false
    try {
      ctx = new AudioContext()
      const src = ctx.createMediaStreamSource(stream), an = ctx.createAnalyser()
      an.fftSize = 512
      src.connect(an)  // analyser only: not connected to the speakers (the <audio> element plays the sound)
      const buf = new Uint8Array(an.fftSize)
      let last = 0
      const tick = (t: number) => {
        if (stopped) return
        if (t - last > 120) {
          last = t
          an.getByteTimeDomainData(buf)
          let sum = 0
          for (const v of buf) { const x = (v - 128) / 128; sum += x * x }
          setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4))
        }
        raf = requestAnimationFrame(tick)
      }
      void ctx.resume().catch(() => undefined)
      raf = requestAnimationFrame(tick)
    } catch { setLevel(0) }
    return () => { stopped = true; cancelAnimationFrame(raf); void ctx?.close().catch(() => undefined) }
  }, [stream, on])
  return level
}

function LevelBar({ level, label }: { level: number; label: string }) {
  return (
    <div className="flex items-center gap-2" aria-label={label} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level * 100)} data-testid="remote-audio-level">
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-ink-700"><span className="block h-full rounded-full bg-emerald-400 transition-[width] duration-100" style={{ width: `${Math.round(level * 100)}%` }} /></span>
    </div>
  )
}

function Chat({ chat, onSend, me, disabled }: { chat: ChatLine[]; onSend: (t: string) => boolean; me: 'officer' | 'customer'; disabled?: boolean }) {
  const [text, setText] = useState('')
  const [unsent, setUnsent] = useState(false)
  const end = useRef<HTMLDivElement | null>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [chat.length])
  return (
    <div className="space-y-2">
      <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-white/[0.07] bg-ink-950/50 p-2 text-sm" aria-live="polite" aria-label="Chat messages">
        {chat.length === 0 && <p className="text-xs text-slate-500">No messages yet.</p>}
        {chat.map((c, i) => <p key={i} className={c.from === me ? 'text-right text-brand-300' : 'text-slate-200'}><span className="text-xs text-slate-500">{c.from === me ? 'You' : c.from === 'officer' ? 'Officer' : 'Customer'}: </span>{c.text}</p>)}
        <div ref={end} />
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const ok = onSend(text); setUnsent(!ok); if (ok) setText('') }}>
        <input className={`${inputCls} !mt-0`} value={text} maxLength={500} placeholder="Type a message" disabled={disabled} onChange={(e) => setText(e.target.value)} aria-label="Message" />
        <button className={btnGhost} type="submit" disabled={disabled || !text.trim()} aria-label="Send message"><Send className="h-4 w-4" /></button>
      </form>
      {unsent && <p className="text-xs text-amber-300" role="status">Not sent: not connected to the live channel. It reconnects on its own; try again in a moment.</p>}
    </div>
  )
}

/** Officer side: the customer's live camera (large), their voice through an explicit audio control, the officer's microphone, and chat. */
export function OfficerCallPanel({ call, running, sessionId }: { call: Call; running: boolean; sessionId: string }) {
  const v = useRef<HTMLVideoElement | null>(null)
  const audio = useRemoteAudio(call.remote)
  const live = call.state === 'connected' || call.state === 'reconnecting'
  const busy = call.state === 'asking' || call.state === 'connecting'
  const hasVideo = Boolean(call.remote?.getVideoTracks().length)
  const level = useLevel(call.remote, live && audio.hasAudio)
  useEffect(() => {  // the video element is MUTED: sound comes from the audio element, so it is never played twice
    const el = v.current
    if (!el) return
    el.srcObject = call.remote
    if (call.remote) void el.play().catch(() => undefined)
  }, [call.remote])
  const { hangUp, state } = call
  useEffect(() => { if (!running && active(state)) hangUp() }, [running, state, hangUp])  // the session ended: so does the call
  const micMuted = call.mic === 'muted'
  return (
    <Card className="space-y-3" >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium text-white"><Video className="mr-2 inline h-4 w-4 text-brand-300" />Customer live</h2>
        <Pill tone={STATE_TONE[call.state]}>{busy && <Spinner className="h-3 w-3" />}{STATE_TEXT[call.state]}</Pill>
      </div>
      <div className="relative aspect-video overflow-hidden rounded-xl border border-white/10 bg-black" data-session-id={sessionId}>
        <video ref={v} playsInline autoPlay muted className="h-full w-full object-cover" aria-label="Customer live video" data-testid="officer-remote-video" />
        {(!live || !hasVideo) && (
          <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-slate-400">
            {live && !hasVideo ? <span><VideoOff className="mx-auto mb-2 h-6 w-6" />Connected, but the customer's camera sends no picture.</span>
              : call.state === 'asking' ? 'The customer is being asked to accept the call…'
              : call.state === 'connecting' ? 'Connecting to the customer…'
              : running ? 'Start a call to see and hear the customer live. They must accept first.'
              : 'Live video is available while the session is running.'}
          </div>)}
        {live && <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white"><span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />Live · not recorded</span>}
      </div>
      {call.detail && <p className="text-xs text-amber-300" role="status">{call.detail}</p>}
      {!call.enabled && <p className="text-xs text-slate-500">Live calls are switched off on this server.</p>}
      <div className="flex flex-wrap items-center gap-2">
        {!live && !busy && <button className={btnPrimary} disabled={!running || !call.enabled} onClick={call.request}><PhoneCall className="h-4 w-4" />Start live call</button>}
        {(live || busy) && <button className={btnDanger} onClick={call.hangUp}><PhoneOff className="h-4 w-4" />End call</button>}
        {live && call.setMicMuted && call.mic !== 'unavailable' && call.mic !== 'none' && (
          <button className={btnGhost} onClick={() => call.setMicMuted?.(!micMuted)} aria-pressed={micMuted}>{micMuted ? <><MicOff className="h-4 w-4" />Unmute my microphone</> : <><Mic className="h-4 w-4" />Mute my microphone</>}</button>)}
        {live && audio.hasAudio && !audio.blocked && (
          <button className={btnGhost} onClick={() => audio.setMuted(!audio.muted)} aria-pressed={audio.muted}>{audio.muted ? <><VolumeX className="h-4 w-4" />Unmute customer</> : <><Volume2 className="h-4 w-4" />Mute customer</>}</button>)}
      </div>
      {live && (
        <div className="space-y-1.5 rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 text-xs text-slate-300">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5">{audio.hasAudio ? <Volume2 className="h-3.5 w-3.5 text-emerald-300" /> : <VolumeX className="h-3.5 w-3.5 text-amber-300" />}
              {!audio.hasAudio ? 'No audio from the customer (their microphone sends nothing).' : audio.blocked ? 'The browser blocked the sound.' : audio.muted ? 'Customer audio muted by you.' : 'Customer audio playing.'}</span>
            {audio.hasAudio && <LevelBar level={level} label="Customer audio level" />}
          </div>
          {audio.blocked && <button className={`${btnPrimary} w-full`} onClick={audio.unblock}><Volume2 className="h-4 w-4" />Click to hear the customer</button>}
          <span className="inline-flex items-center gap-1.5">{call.mic === 'on' ? <><Mic className="h-3.5 w-3.5 text-emerald-300" />Your microphone is on: the customer hears you.</>
            : call.mic === 'muted' ? <><MicOff className="h-3.5 w-3.5 text-amber-300" />Your microphone is muted: the customer cannot hear you.</>
            : <><MicOff className="h-3.5 w-3.5 text-amber-300" />{call.micDetail || 'Your microphone is not in the call: the customer cannot hear you.'}</>}</span>
        </div>)}
      <audio ref={audio.ref} autoPlay className="hidden" data-testid="officer-remote-audio" />
      <p className="text-xs text-slate-500">The customer is asked first and must accept. Video and sound go directly between the two browsers; the server only relays the connection setup and records nothing.{call.relayConfigured === false ? ' No TURN relay is configured, so very strict networks may not connect.' : ''}</p>
      <Chat chat={call.chat} onSend={call.sendChat} me="officer" disabled={!running} />
    </Card>
  )
}

/** Customer side: a prompt when the officer asks to talk, the officer's voice (with an explicit control if autoplay is blocked), and a small chat. */
export function CustomerCallBar({ call, active: camOn }: { call: Call; active: boolean }) {
  const audio = useRemoteAudio(call.remote)
  const live = call.state === 'connected' || call.state === 'connecting' || call.state === 'reconnecting'
  return (
    <div className="space-y-3">
      <audio ref={audio.ref} autoPlay className="hidden" />
      {call.incoming && !live && (
        <div role="alertdialog" aria-label="Officer call request" className="rounded-xl border border-brand-400/40 bg-brand-400/[0.08] p-4">
          <p className="font-medium text-white">The reviewing officer would like to see and talk to you.</p>
          <p className="mt-1 text-sm text-slate-300">If you accept, the officer sees your live camera and hears you, and you hear the officer. Nothing is recorded. You can end it any time.</p>
          <div className="mt-3 flex gap-2"><button className={btnPrimary} disabled={!camOn} onClick={call.accept}><PhoneCall className="h-4 w-4" />Accept</button><button className={btnGhost} onClick={call.decline}>Not now</button></div>
          {!camOn && <p className="mt-2 text-xs text-amber-300">Start your camera first.</p>}
        </div>)}
      {live && (
        <div className="space-y-2 rounded-xl border border-emerald-400/30 bg-emerald-400/[0.07] p-3 text-sm text-emerald-200">
          <div className="flex items-center justify-between gap-2"><span><PhoneCall className="mr-2 inline h-4 w-4" />{call.state === 'connected' ? 'In a call with the officer. The officer sees your camera.' : call.state === 'reconnecting' ? 'Connection unstable, trying to recover…' : 'Connecting to the officer…'}</span>
            <button className={btnDanger} onClick={call.hangUp}><PhoneOff className="h-4 w-4" />End</button></div>
          {audio.blocked && <button className={`${btnPrimary} w-full`} onClick={audio.unblock}><Volume2 className="h-4 w-4" />Click to hear the officer</button>}
          {call.state === 'connected' && !audio.hasAudio && <p className="text-xs text-emerald-200/80">The officer's microphone is off, so you will not hear them; they can still type in the chat.</p>}
        </div>)}
      {call.detail && !live && <p className="text-xs text-amber-300">{call.detail}</p>}
      <div className="space-y-1"><p className="text-xs font-medium text-slate-300">Chat with the reviewing officer</p><Chat chat={call.chat} onSend={call.sendChat} me="customer" /></div>
    </div>
  )
}
