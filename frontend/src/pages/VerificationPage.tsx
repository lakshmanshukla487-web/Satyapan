import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Camera, CheckCircle2, Hourglass, Lock, Mic, MicOff, ShieldCheck, Square } from 'lucide-react'
import { service } from '../features/services'
import { useCall } from '../features/call/useCall'
import { useMediaStream } from '../hooks/useMediaStream'
import { useConnectionStatus } from '../hooks/useConnectionStatus'
import { useCustomerChannel } from '../hooks/useCustomerChannel'
import { Card, ErrorBox, Pill, SimBanner, Spinner, btnGhost, btnPrimary } from '../components/ui'
import { Stepper } from '../components/Stepper'
import { DocumentsStep } from '../components/DocumentsStep'
import { PhotoStep } from '../components/PhotoStep'
import { CustomerCallBar } from '../components/CallPanels'
import { captureFrame, captureFrameAt, recordAvClip, recordWav } from '../utils/capture'
import { guideEyeScan, measure, type Measured } from '../utils/challengeDetector'
import { collectProbe } from '../utils/integrityProbe'
import { samplePulse } from '../utils/pulseSampler'
import { env } from '../config/env'
import type { Challenge, ChallengeStatus, WsEvent } from '../types'

// The customer is never told whether a step "passed": results stay with the officer, so a fraudster cannot tune an attack against them.
const tone: Record<ChallengeStatus, 'green' | 'red' | 'amber' | 'slate' | 'cyan'> = { passed: 'green', failed: 'red', in_progress: 'cyan', pending: 'slate', unavailable: 'amber', awaiting_approval: 'amber', done: 'slate' }
const statusText = (s: ChallengeStatus) => (s === 'awaiting_approval' ? 'with reviewer' : s === 'done' ? 'done' : s.replace('_', ' '))
const MOCK_TOTAL = 3 // demo mode only: the simulated flow has three steps
const MIN_SESSION_S = 90 // the backend cannot give GREEN to shorter sessions, so the Finish button unlocks after this long (backend MIN_SESSION_SECONDS)
const MIN_FRAMES = 2, MIN_AUDIO = 1 // samples the backend needs before the session ends, or detectors report "no samples" (GREY)
const GAP_SECONDS = 4 // breathing space between one challenge and the next
const GAP_SECONDS_REVIEWED = 2 // when an officer approves every step, the review itself already gives breathing space
const PULSE_SECONDS = 12 // camera and lighting check at the start (pipeline integrity probe and pulse trace)
const TAGGED_FRAME_MS = 450 // while a head turn or blink is in progress the server needs a dense series of frames to cross-check it
const SHOWN = 5 // challenge history lines shown
const STEPS = ['Request', 'Documents', 'Your photo', 'Live check']
type Phase = 'consent' | 'waiting' | 'documents' | 'photo' | 'live' | 'done' | 'ended' | 'declined'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const msg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const NEUTRAL_END = 'This verification has ended. We will complete it another way. You do not need to do anything else here.'
const NEUTRAL_DECLINED = 'Your request could not be taken forward right now. We will contact you about the next step. You do not need to do anything else here.'
async function videoReady(v: HTMLVideoElement | null, ms = 4000) {
  const end = Date.now() + ms
  while (v && v.readyState < 2 && Date.now() < end) await sleep(100)
}
const isPoseKind = (c?: Challenge) => c?.kind === 'head_left' || c?.kind === 'head_right' || c?.kind === 'blink'

export default function VerificationPage() {
  const media = useMediaStream()
  const real = !env.useMocks
  const live = useRef<string | null>(null) // id of the session currently open on the backend
  const started = useRef(false) // /start was accepted for this session
  const mockList = useRef<Challenge[]>([])
  const calibration = useRef<AbortController | null>(null)
  const syncing = useRef(false)
  const reviewed = useRef(false) // an officer approves each step (learned from the first challenge)
  const submitting = useRef(false)
  const approving = useRef(false)
  const finishing = useRef(false)
  const framesSent = useRef(0), audioSent = useRef(0), audioBusy = useRef(false), avBusy = useRef(false)
  const frameBusy = useRef({ plain: false, tagged: false })
  const startedAt = useRef(0)
  const eventRef = useRef<(e: WsEvent) => void>(() => undefined)
  const [phase, setPhase] = useState<Phase>('consent')
  const [consent, setConsent] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [challenges, setChallenges] = useState<Challenge[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [liveMsg, setLiveMsg] = useState('')
  const [calibrating, setCalibrating] = useState(false)
  const [endMsg, setEndMsg] = useState(NEUTRAL_END)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const conn = useConnectionStatus('idle', Boolean(err))
  const active = media.state === 'active'
  const current = challenges.find((c) => c.status === 'in_progress')
  const waiting = challenges.find((c) => c.status === 'awaiting_approval')
  const waitingId = waiting?.id
  const passedMock = challenges.filter((c) => c.status === 'passed').length
  const stepIndex = phase === 'consent' || phase === 'waiting' || phase === 'declined' ? 0 : phase === 'documents' ? 1 : phase === 'photo' ? 2 : phase === 'live' ? 3 : 4

  const channel = useCustomerChannel(phase === 'waiting' || phase === 'live' ? sessionId : null, (e) => eventRef.current(e))
  const call = useCall('customer', channel.send, () => media.streamRef.current)

  /* ---------------------------------------------------------------- session lifecycle */
  const begin = async () => {
    setErr(null); setNote(''); setBusy(true)
    try {
      const s = await service.createSession()
      live.current = s.sessionId; started.current = false; mockList.current = s.challenges
      setSessionId(s.sessionId)
      if (s.approval === 'pending') setPhase('waiting') // an officer must approve first; nothing else is possible until then
      else { await service.recordConsent(s.sessionId); setPhase('documents') }
    } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  const proceedAfterApproval = async (id: string) => { // the tick-box was ticked before asking; consent is recorded now that the request is approved
    if (approving.current || live.current !== id) return
    approving.current = true
    try { await service.recordConsent(id); if (live.current === id) { setErr(null); setPhase('documents') } } catch (e) { setErr(msg(e)) } finally { approving.current = false }
  }
  const checkApproval = async (id: string) => {
    try {
      const m = await service.getMySession(id)
      if (live.current !== id) return
      if (m.approval === 'approved' || m.approval === 'not_required') await proceedAfterApproval(id)
      else if (m.approval === 'rejected' || m.approval === 'expired' || m.status === 'cancelled') { live.current = null; setEndMsg(NEUTRAL_DECLINED); setPhase('declined') }
    } catch { /* offline: try again next time */ }
  }
  const endSession = (message?: string) => { // an officer ended the check
    calibration.current?.abort(); live.current = null; call.hangUp(); media.stop()
    setEndMsg(message || NEUTRAL_END); setPhase('ended')
  }
  const checkEnded = async (id: string) => {
    try { const mine = await service.listMySessions(); if (live.current === id && mine.find((x) => x.id === id)?.status === 'terminated') endSession() } catch { /* offline: try again next time */ }
  }
  const reset = () => {
    calibration.current?.abort(); media.stop()
    setSessionId(null); setChallenges([]); setPhase('consent'); setErr(null); setNote(''); setLiveMsg(''); setCalibrating(false); setElapsed(0); started.current = false; reviewed.current = false; finishing.current = false
    framesSent.current = 0; audioSent.current = 0
  }
  const stop = async () => {
    if (live.current) { await service.cancelSession(live.current).catch(() => undefined); live.current = null }
    reset()
  }

  /* ---------------------------------------------------------------- live step: challenges continue until the person finishes */
  const pause = async (id: string, seconds: number, label: string) => { // counts down on screen; false if the session was stopped or replaced meanwhile
    for (let n = seconds; n > 0; n--) { if (live.current !== id) return false; setLiveMsg(`${label} ${n}s...`); await sleep(1000) }
    setLiveMsg('')
    return live.current === id
  }
  const requestChallenge = async (id: string, keep: Challenge[]) => {
    const c = await service.issueChallenge(id) // returns the one still open, if any, so a retry never piles challenges up
    if (c.status === 'awaiting_approval') reviewed.current = true
    setChallenges([...keep.filter((k) => k.id !== c.id), c])
  }
  // Camera probe (pipeline integrity) and pulse trace: only numbers leave the browser. Runs while the first challenge waits for review.
  const calibrate = async (id: string) => {
    const video = media.videoRef.current, stream = media.streamRef.current
    if (!video || !stream) return
    const ac = new AbortController(); calibration.current = ac
    setCalibrating(true); setLiveMsg('Checking camera and lighting. Look at the camera and hold still...')
    try {
      await videoReady(video)
      const [probe, trace] = await Promise.allSettled([collectProbe(stream, video), samplePulse(video, PULSE_SECONDS, ac.signal)])
      if (ac.signal.aborted || live.current !== id) return
      if (probe.status === 'fulfilled') await service.sendIntegrityProbe(id, probe.value).catch(() => undefined)
      if (trace.status === 'fulfilled' && trace.value) await service.sendPulse(id, trace.value.fps, trace.value.rgb).catch(() => undefined)
    } finally { setCalibrating(false); setLiveMsg('') }
  }
  const startLive = async () => {
    const id = sessionId
    if (!id) return
    setErr(null); setNote(''); setBusy(true); framesSent.current = 0; audioSent.current = 0
    try {
      await media.start()
      if (!media.streamRef.current) return // the camera or microphone is unavailable; the message is shown and nothing has started
      if (!started.current) { await service.startSession(id); started.current = true; startedAt.current = Date.now() } // the backend refuses until the documents are checked
      if (real) { void calibrate(id).catch(() => undefined); await requestChallenge(id, []) }
      else setChallenges(mockList.current.map((c, i) => ({ ...c, status: i === 0 ? 'in_progress' : 'pending' })))
    } catch (e) { setErr(msg(e)); media.stop(); void checkEnded(id) } finally { setBusy(false) }
  }

  // Real mode: upload one frame / one audio clip. Counted only once the backend has accepted it.
  const sendFrame = async (id: string, challengeId?: string) => {
    const k = challengeId ? 'tagged' : 'plain'
    if (frameBusy.current[k]) return
    frameBusy.current[k] = true
    try { const b = await captureFrame(media.videoRef.current); if (b) { await service.uploadFrame(id, b, challengeId); if (!challengeId) framesSent.current++ } } finally { frameBusy.current[k] = false }
  }
  const sendAudio = async (id: string, seconds: number) => {
    const st = media.streamRef.current
    if (!st || audioBusy.current) return
    audioBusy.current = true
    try { await service.uploadAudio(id, await recordWav(st, seconds)); audioSent.current++ } finally { audioBusy.current = false }
  }
  // A short video+voice clip while the customer speaks (phrase challenge): lets the server check that the lips match the voice.
  const sendAvClip = async (id: string) => {
    const v = media.videoRef.current, st = media.streamRef.current
    if (!v || !st || avBusy.current) return
    avBusy.current = true
    try { const c = await recordAvClip(v, st, 4); if (live.current === id && c.frames.length >= 20) await service.uploadAvSync(id, c.frames, c.times, c.wav) } finally { avBusy.current = false }
  }
  // Make sure the minimum samples have landed before the session ends, or the officer would see GREY (insufficient evidence).
  const flushEvidence = async (id: string) => {
    for (let i = 0; i < 80 && audioBusy.current; i++) await sleep(100)
    const jobs: Promise<unknown>[] = []
    jobs.push((async () => { for (let n = framesSent.current; n < MIN_FRAMES; n++) { await sendFrame(id); await sleep(400) } })())
    if (audioSent.current < MIN_AUDIO) jobs.push(sendAudio(id, 4))
    await Promise.allSettled(jobs)
  }
  const finish = async () => {
    const id = live.current
    if (!id || finishing.current) return
    finishing.current = true; setBusy(true)
    try {
      call.hangUp(); calibration.current?.abort()
      if (real) { setLiveMsg('Finishing: sending the last samples for analysis...'); await flushEvidence(id) }
      await service.completeSession(id); live.current = null
      media.stop(); setPhase('done')
    } catch (e) { setErr(msg(e)); finishing.current = false } finally { setBusy(false) }
  }
  // Mock mode only: simulated outcomes.
  const advance = (ok: boolean) => {
    const next = challenges.map((c) => ({ ...c }))
    const i = next.findIndex((c) => c.status === 'in_progress'); if (i < 0) return
    next[i].status = ok ? 'passed' : 'failed'; next[i].completedAt = new Date().toISOString()
    if (next[i + 1]) next[i + 1].status = 'in_progress'
    setChallenges(next)
    if (!next[i + 1]) void finish()
  }
  const afterAnswer = async (id: string, list: Challenge[]) => {
    setChallenges(list)
    if (finishing.current) return
    if (!(await pause(id, reviewed.current ? GAP_SECONDS_REVIEWED : GAP_SECONDS, 'Next step in'))) return
    await requestChallenge(id, list)
  }
  const drainTaggedFrames = async () => { for (let i = 0; i < 30 && frameBusy.current.tagged; i++) await sleep(50) }
  // Real mode: measure in the browser, then send the measurements. The server cross-checks head turns against its own measurement of the frames.
  const submitWith = async (cur: Challenge, measured: Measured) => {
    const id = sessionId
    if (!id || submitting.current) return
    submitting.current = true; setBusy(true); setErr(null); setLiveMsg('')
    try {
      await drainTaggedFrames()
      let list: Challenge[]
      try { const res = await service.submitChallenge(id, cur.id, measured); list = challenges.map((c) => (c.id === cur.id ? res : c)) }
      catch (e) { if (!msg(e).includes('expired')) throw e; await requestChallenge(id, challenges.filter((c) => c.id !== cur.id)); setNote('That step timed out, so a new one was requested.'); return }
      setNote('')
      await afterAnswer(id, list)
    } catch (e) { setErr(msg(e)); void checkEnded(id) } finally { submitting.current = false; setBusy(false) }
  }
  // Eye scan: guide the person close to the camera, take 5 close-up frames, let the server decide.
  const submitEyeScan = async (cur: Challenge, ac: AbortController) => {
    const id = sessionId, video = media.videoRef.current
    if (!id || !video || submitting.current) return
    submitting.current = true; setBusy(true); setErr(null)
    try {
      await guideEyeScan(video, setLiveMsg, ac.signal).catch(() => false) // if the face detector is missing we still take the frames
      if (ac.signal.aborted) return
      setLiveMsg('Capturing... keep your eyes wide open.')
      const frames: Blob[] = []
      for (let i = 0; i < 5 && !ac.signal.aborted; i++) { const b = await captureFrameAt(video, 1280, 0.92); if (b) frames.push(b); await sleep(350) }
      if (ac.signal.aborted) return
      setLiveMsg('')
      let list: Challenge[]
      try { await service.submitEyeScan(id, cur.id, frames); list = challenges.map((c) => (c.id === cur.id ? { ...c, status: 'done' as const } : c)) }
      catch (e) { if (!msg(e).includes('expired')) throw e; await requestChallenge(id, challenges.filter((c) => c.id !== cur.id)); setNote('That step timed out, so a new one was requested.'); return }
      await afterAnswer(id, list)
    } catch (e) { setErr(msg(e)); void checkEnded(id) } finally { submitting.current = false; setBusy(false) }
  }

  /* ---------------------------------------------------------------- waiting for the reviewing officer */
  const syncWaiting = async () => {
    const id = sessionId, wid = waitingId
    if (!id || !wid || syncing.current || live.current !== id) return
    syncing.current = true
    try {
      const cur = await service.currentChallenge(id)
      if (live.current !== id) return
      if (cur && cur.id === wid && cur.status === 'awaiting_approval') return // still with the officer
      if (cur) { setChallenges((p) => p.map((c) => (c.id === wid ? cur : c))); return } // released, or replaced by a fresh request
      setNote('The review request timed out, so a new one was sent.') // nothing open any more
      await requestChallenge(id, challenges.filter((c) => c.id !== wid))
    } catch (e) { setErr(msg(e)); void checkEnded(id) } finally { syncing.current = false }
  }
  eventRef.current = (e: WsEvent) => {
    if (e.event === 'session.terminated') endSession((e.data as { message?: string } | null)?.message)
    else if (e.event === 'session.approved' || e.event === 'session.rejected') { if (sessionId) void checkApproval(sessionId) }
    else if (e.event === 'challenge.released') void syncWaiting()
    else call.onEvent(e)
  }
  useEffect(() => { // waiting for the officer to approve the request: the socket tells us, polling is the fallback
    if (!real || phase !== 'waiting' || !sessionId) return
    const id = sessionId
    void checkApproval(id)
    const t = setInterval(() => void checkApproval(id), 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, phase, sessionId])
  useEffect(() => { // polling fallback in case the socket drops
    if (!real || phase !== 'live' || !waitingId) return
    const t = setInterval(() => void syncWaiting(), 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, phase, waitingId, sessionId])
  useEffect(() => { // and a slow check that an officer has not ended the session
    if (!real || phase !== 'live' || !sessionId) return
    const id = sessionId
    const t = setInterval(() => void checkEnded(id), 6000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, phase, sessionId])
  useEffect(() => { // how long the check has been running (the Finish button unlocks after the minimum length)
    if (phase !== 'live' || !active) return
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 1000)
    return () => clearInterval(t)
  }, [phase, active])

  /* ---------------------------------------------------------------- measurement and sampling */
  useEffect(() => {
    const video = media.videoRef.current
    if (!real || !active || !sessionId || !current || !video || calibrating) return
    const ac = new AbortController()
    if (current.kind === 'eye_scan') { void submitEyeScan(current, ac); return () => ac.abort() }
    if (current.kind === 'phrase') { const t = setTimeout(() => void sendAvClip(sessionId).catch(() => undefined), 1500); ac.signal.addEventListener('abort', () => clearTimeout(t)) }
    measure(current, video, setLiveMsg, ac.signal)
      .then((m) => { if (!ac.signal.aborted) void submitWith(current, m) })
      .catch((e) => { setNote(`Challenge detection unavailable: ${msg(e)}. Run "npm run setup:assets" in the frontend folder.`); if (!ac.signal.aborted) void submitWith(current, {}) })
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, active, sessionId, current?.id, calibrating])
  useEffect(() => { // a dense frame series, tagged with the challenge, while a head turn or blink is being done (server-side cross-check)
    if (!real || !active || !sessionId || !current || !isPoseKind(current) || calibrating) return
    const id = sessionId, cid = current.id
    const t = setInterval(() => void sendFrame(id, cid).catch(() => undefined), TAGGED_FRAME_MS)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, active, sessionId, current?.id, calibrating])
  useEffect(() => { // first samples right away, then a frame every 3 s and a 5 s WAV clip every 6 s while capturing
    if (!real || !active || !sessionId) return
    const id = sessionId
    const frame = () => void sendFrame(id).catch((e) => setNote(`Frame upload: ${msg(e)}`))
    const audio = () => void sendAudio(id, 5).catch((e) => setNote(`Audio upload: ${msg(e)}`))
    const t1 = setTimeout(audio, 300), t2 = setTimeout(frame, 800), fi = setInterval(frame, 3000), ai = setInterval(audio, 6000)
    return () => { clearTimeout(t1); clearTimeout(t2); clearInterval(fi); clearInterval(ai) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [real, active, sessionId])
  useEffect(() => () => { if (live.current) void service.cancelSession(live.current).catch(() => undefined) }, []) // leaving the page cancels

  /* ---------------------------------------------------------------- end screens */
  if (phase === 'done') return (
    <Card className="mx-auto max-w-lg space-y-3 py-8 text-center"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-400" /><h1 className="text-xl font-semibold text-white">{real ? 'Verification submitted' : 'Demo verification complete'}</h1>
      <p className="text-sm text-slate-400">{real ? `Session ${sessionId} was sent for officer review. You can follow its status on your dashboard. The camera and microphone were released.` : `Session ${sessionId} ended. This was a simulated flow: nothing was analysed or uploaded.`}</p>
      <div className="flex justify-center gap-3"><button className={btnGhost} onClick={reset}>Start again</button><Link to="/dashboard" className={btnPrimary}>My dashboard</Link></div></Card>
  )
  if (phase === 'ended' || phase === 'declined') return (
    <Card className="mx-auto max-w-lg space-y-3 py-8 text-center"><ShieldCheck className="mx-auto h-12 w-12 text-slate-400" /><h1 className="text-xl font-semibold text-white">{phase === 'declined' ? 'Request not taken forward' : 'This check has ended'}</h1>
      <p className="text-sm text-slate-400">{endMsg}</p><p className="text-xs text-slate-500">The camera and microphone were released.</p>
      <div className="flex justify-center"><Link to="/dashboard" className={btnPrimary} onClick={reset}>My dashboard</Link></div></Card>
  )

  const shown = challenges.filter((c) => c.status !== 'awaiting_approval').slice(-SHOWN)
  const canFinish = !real || elapsed >= MIN_SESSION_S
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div><h1 className="text-2xl font-semibold text-white">Identity verification</h1><p className="text-sm text-slate-400">A bank officer approves your request, then you upload documents, take a starting photo and complete a live check.</p></div>
      <Stepper steps={STEPS} current={stepIndex} />
      {env.useMocks && <SimBanner text="Demo flow: documents and challenges are simulated. Nothing is analysed or uploaded." />}

      {phase === 'consent' && (
        <Card className="mx-auto max-w-2xl space-y-4">
          <div className="flex items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-400/10 text-brand-300"><Lock className="h-5 w-5" /></span>
            <div><h2 className="font-medium text-white">Your consent</h2><p className="mt-1 text-sm text-slate-400">First you ask a bank officer for permission to verify. When it is approved you upload your documents and a starting photo. For the live check, Satyapan uses your camera and microphone, and the officer may ask to see and talk to you live. Capture starts only when you press the start button and stops when you press Stop or leave this page. Video and audio are analysed and not stored.</p></div></div>
          <label className="flex items-start gap-2 text-sm text-slate-200"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />I agree to the processing of my documents and photo, to camera and microphone use, and to an officer watching the live check, for this verification session.</label>
          {err && <ErrorBox message={err} />}
          <button className={btnPrimary} disabled={!consent || busy} onClick={() => void begin()}>{busy ? <Spinner /> : null}Ask an officer to start my verification</button>
        </Card>)}

      {phase === 'waiting' && (
        <Card className="mx-auto max-w-2xl space-y-3 py-8 text-center" >
          <Hourglass className="mx-auto h-10 w-10 text-amber-300" /><h2 className="text-lg font-medium text-white" aria-live="polite">Waiting for an officer to approve your request</h2>
          <p className="text-sm text-slate-400">You can keep this page open. As soon as an officer approves, the next step appears here automatically. Requests that wait too long expire and can be made again.</p>
          <div className="flex justify-center gap-2"><Pill tone={channel.state === 'open' ? 'green' : 'slate'}>{channel.state === 'open' ? 'Connected' : 'Checking every few seconds'}</Pill></div>
          {err && <ErrorBox message={err} />}
          <div className="flex justify-center"><button className={btnGhost} onClick={() => void stop()}>Cancel my request</button></div>
        </Card>)}

      {phase === 'documents' && sessionId && (
        <DocumentsStep sessionId={sessionId} onAccepted={() => { setErr(null); setPhase('photo') }} />)}

      {phase === 'photo' && sessionId && (
        <PhotoStep sessionId={sessionId} onAccepted={() => { setErr(null); setPhase('live') }} />)}

      {phase === 'live' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="relative aspect-video overflow-hidden rounded-2xl border border-white/10 bg-black shadow-card">
              <video ref={media.videoRef} muted playsInline className="h-full w-full object-cover" aria-label="Camera preview" />
              {!active && <div className="absolute inset-0 grid place-items-center text-sm text-slate-500"><span><Camera className="mr-2 inline h-5 w-5" />Camera is off</span></div>}
              {active && <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white"><span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />Live</span>}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button className={btnPrimary} disabled={active || busy || media.state === 'requesting'} onClick={() => void startLive()}>{busy && !active ? <Spinner /> : <Camera className="h-4 w-4" />}Start camera and begin</button>
              <button className={btnGhost} disabled={!active} onClick={() => void stop()}><Square className="h-4 w-4" />Stop</button>
              <Pill tone={media.micActive ? 'green' : 'slate'}>{media.micActive ? <><Mic className="mr-1 inline h-3 w-3" />Microphone on</> : <><MicOff className="mr-1 inline h-3 w-3" />Microphone off</>}</Pill>
            </div>
            {(media.message || err) && <ErrorBox message={media.message || err || ''} />}
            {note && <p className="text-xs text-amber-300">{note}</p>}
            <CustomerCallBar call={call} active={active} />
            <p className="text-xs text-slate-500">Documents and photo accepted. Press the button, allow camera and microphone access, and keep your face in view and in good light.</p>
          </div>
          <Card className="space-y-4">
            <div className="flex items-center justify-between"><h2 className="font-medium text-white">Live check</h2><div className="flex gap-2"><Pill tone={conn.tone}>{conn.label}</Pill><Pill tone={active ? 'green' : 'slate'}>{active ? 'Capturing' : 'Not capturing'}</Pill></div></div>
            <p className="text-xs text-slate-500">Session ID: <span className="font-mono">{sessionId ?? 'Not started'}</span>{active && real ? <> · running for <span className="tabular-nums">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span></> : null}</p>
            {!real && <div role="progressbar" aria-label="Challenges completed" aria-valuenow={passedMock} aria-valuemin={0} aria-valuemax={MOCK_TOTAL} className="h-2 overflow-hidden rounded-full bg-ink-700"><div className="h-2 rounded-full bg-gradient-to-r from-brand-400 to-emerald-400 transition-all" style={{ width: `${(passedMock / MOCK_TOTAL) * 100}%` }} /></div>}
            {real && active && <div role="progressbar" aria-label="Minimum check time" aria-valuenow={Math.min(elapsed, MIN_SESSION_S)} aria-valuemin={0} aria-valuemax={MIN_SESSION_S} className="h-2 overflow-hidden rounded-full bg-ink-700"><div className="h-2 rounded-full bg-gradient-to-r from-brand-400 to-emerald-400 transition-all" style={{ width: `${Math.min(100, (elapsed / MIN_SESSION_S) * 100)}%` }} /></div>}

            {!active && challenges.length === 0 && <p className="text-sm text-slate-400">The steps appear after you start the camera.</p>}
            {active && calibrating && <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-200" aria-live="polite"><Spinner className="h-5 w-5 text-brand-300" />{liveMsg || 'Checking camera and lighting...'}</div>}
            {active && !calibrating && waiting && !current && (
              <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.07] p-4" aria-live="polite"><div className="flex items-center gap-3"><Hourglass className="h-6 w-6 shrink-0 text-amber-300" />
                <div><p className="font-medium text-white">Waiting for the reviewing officer</p><p className="text-sm text-slate-400">Your next step is being prepared and checked. It appears here as soon as it is released. Stay in front of the camera.</p></div></div></div>)}
            {active && !calibrating && current && real && (
              <div className="rounded-xl border border-brand-400/30 bg-brand-400/[0.07] p-4" aria-live="polite"><p className="text-xs uppercase tracking-wider text-brand-300">Do this now</p><p className="mt-1 text-xl font-medium text-white">{current.prompt}</p><p className="mt-2 text-sm text-slate-300">{liveMsg || 'Preparing detection...'}</p></div>)}
            {active && !calibrating && !current && !waiting && liveMsg && <p className="text-sm text-slate-200" aria-live="polite">{liveMsg}</p>}

            {shown.length > 0 && <ul className="space-y-2">{shown.map((c) => <li key={c.id} className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.07] p-3 text-sm"><span className={c.status === 'in_progress' ? 'text-white' : 'text-slate-400'}>{c.prompt}</span><Pill tone={real ? (c.status === 'in_progress' ? 'cyan' : 'slate') : tone[c.status]}>{statusText(c.status)}</Pill></li>)}</ul>}
            {active && real && (
              <div className="space-y-2 border-t border-white/[0.06] pt-3">
                <p className="text-sm text-slate-300">New steps keep appearing for as long as the check runs. When the time bar is full you can finish.</p>
                <div className="flex flex-wrap gap-2">
                  <button className={btnPrimary} disabled={busy || !canFinish} onClick={() => void finish()}>{busy && finishing.current ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}{canFinish ? 'Finish verification' : `Finish in ${Math.max(0, MIN_SESSION_S - elapsed)}s`}</button>
                  <button className={btnGhost} disabled={busy || !current || current.kind === 'eye_scan'} onClick={() => current && void submitWith(current, {})}>Skip this step</button>
                </div>
                <p className="text-xs text-slate-500">Head turns and blinks are measured in your browser (MediaPipe) and checked again on the server. Spoken phrases use your browser's speech service, which may send audio to its provider. Results are never shown to you.</p>
              </div>)}
            {active && !real && <div className="flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-3"><span className="text-xs text-slate-500">Demo controls:</span><button className={btnGhost} onClick={() => advance(true)}>Simulate pass</button><button className={btnGhost} onClick={() => advance(false)}>Simulate fail</button></div>}
          </Card>
        </div>)}
    </div>
  )
}
