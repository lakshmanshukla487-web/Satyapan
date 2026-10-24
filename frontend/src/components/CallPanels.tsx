import { useEffect, useRef, useState } from 'react'
import { Mic, PhoneCall, PhoneOff, Send, Video } from 'lucide-react'
import type { ChatLine } from '../features/call/useCall'
import type { CallState } from '../features/call/liveCall'
import { Card, Pill, btnDanger, btnGhost, btnPrimary, inputCls } from './ui'

type Call = { state: CallState; detail: string; remote: MediaStream | null; incoming: boolean; chat: ChatLine[]; enabled: boolean; request: () => void; accept: () => void; decline: () => void; hangUp: () => void; sendChat: (t: string) => boolean }

function Chat({ chat, onSend, me, disabled }: { chat: ChatLine[]; onSend: (t: string) => boolean; me: 'officer' | 'customer'; disabled?: boolean }) {
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement | null>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [chat.length])
  return (
    <div className="space-y-2">
      <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-white/[0.07] bg-ink-950/50 p-2 text-sm" aria-live="polite" aria-label="Chat messages">
        {chat.length === 0 && <p className="text-xs text-slate-500">No messages yet.</p>}
        {chat.map((c, i) => <p key={i} className={c.from === me ? 'text-right text-brand-300' : 'text-slate-200'}><span className="text-xs text-slate-500">{c.from === me ? 'You' : c.from === 'officer' ? 'Officer' : 'Customer'}: </span>{c.text}</p>)}
        <div ref={end} />
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (onSend(text)) setText('') }}>
        <input className={`${inputCls} !mt-0`} value={text} maxLength={500} placeholder="Type a message" disabled={disabled} onChange={(e) => setText(e.target.value)} aria-label="Message" />
        <button className={btnGhost} type="submit" disabled={disabled || !text.trim()} aria-label="Send message"><Send className="h-4 w-4" /></button>
      </form>
    </div>
  )
}

/** Officer side: watch the customer's live video, talk to them, and chat. Only works while the session is running. */
export function OfficerCallPanel({ call, running }: { call: Call; running: boolean }) {
  const v = useRef<HTMLVideoElement | null>(null)
  useEffect(() => { if (v.current) { v.current.srcObject = call.remote; if (call.remote) void v.current.play().catch(() => undefined) } }, [call.remote])
  const live = call.state === 'connected', busy = call.state === 'asking' || call.state === 'connecting'
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between"><h2 className="font-medium text-white"><Video className="mr-2 inline h-4 w-4 text-brand-300" />Live call</h2>
        <Pill tone={live ? 'green' : busy ? 'amber' : 'slate'}>{live ? 'Connected' : call.state === 'asking' ? 'Waiting for the customer to accept' : call.state === 'connecting' ? 'Connecting' : call.state === 'failed' ? 'Not connected' : 'Not in a call'}</Pill></div>
      <div className="relative aspect-video overflow-hidden rounded-xl border border-white/10 bg-black">
        <video ref={v} playsInline autoPlay className="h-full w-full object-cover" aria-label="Customer live video" />
        {!live && <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-slate-500">{running ? 'Start a call to see the customer live and talk to them.' : 'Live video is available while the session is running.'}</div>}
      </div>
      {call.detail && <p className="text-xs text-amber-300">{call.detail}</p>}
      {!call.enabled && <p className="text-xs text-slate-500">Live calls are switched off on this server.</p>}
      <div className="flex flex-wrap gap-2">
        {!live && !busy && <button className={btnPrimary} disabled={!running || !call.enabled} onClick={call.request}><PhoneCall className="h-4 w-4" />Start live call</button>}
        {(live || busy) && <button className={btnDanger} onClick={call.hangUp}><PhoneOff className="h-4 w-4" />End call</button>}
        {live && <span className="inline-flex items-center gap-1 text-xs text-slate-400"><Mic className="h-3 w-3" />Your microphone is on; the customer hears you.</span>}
      </div>
      <p className="text-xs text-slate-500">The customer is asked first and must accept. Video goes directly between the browsers; the server only relays the connection setup.</p>
      <Chat chat={call.chat} onSend={call.sendChat} me="officer" disabled={!running} />
    </Card>
  )
}

/** Customer side: a prompt when the officer asks to talk, the officer's voice, and a small chat. */
export function CustomerCallBar({ call, active }: { call: Call; active: boolean }) {
  const a = useRef<HTMLAudioElement | null>(null)
  useEffect(() => { if (a.current) { a.current.srcObject = call.remote; if (call.remote) void a.current.play().catch(() => undefined) } }, [call.remote])
  const live = call.state === 'connected' || call.state === 'connecting'
  return (
    <div className="space-y-3">
      <audio ref={a} autoPlay />
      {call.incoming && !live && (
        <div role="alertdialog" aria-label="Officer call request" className="rounded-xl border border-brand-400/40 bg-brand-400/[0.08] p-4">
          <p className="font-medium text-white">The reviewing officer would like to see and talk to you.</p>
          <p className="mt-1 text-sm text-slate-300">If you accept, the officer sees your live camera and you hear the officer. You can end it any time.</p>
          <div className="mt-3 flex gap-2"><button className={btnPrimary} disabled={!active} onClick={call.accept}><PhoneCall className="h-4 w-4" />Accept</button><button className={btnGhost} onClick={call.decline}>Not now</button></div>
          {!active && <p className="mt-2 text-xs text-amber-300">Start your camera first.</p>}
        </div>)}
      {live && <div className="flex items-center justify-between rounded-xl border border-emerald-400/30 bg-emerald-400/[0.07] p-3 text-sm text-emerald-200"><span><PhoneCall className="mr-2 inline h-4 w-4" />{call.state === 'connected' ? 'In a call with the officer' : 'Connecting to the officer...'}</span><button className={btnDanger} onClick={call.hangUp}><PhoneOff className="h-4 w-4" />End</button></div>}
      {call.detail && !live && <p className="text-xs text-amber-300">{call.detail}</p>}
      {(call.chat.length > 0 || live || call.incoming) && <Chat chat={call.chat} onSend={call.sendChat} me="customer" />}
    </div>
  )
}
