import { useEffect, useRef, useState } from 'react'
import { Camera, CheckCircle2, Eye, UploadCloud } from 'lucide-react'
import { service } from '../features/services'
import { captureFrameAt } from '../utils/capture'
import type { ReferenceResult } from '../types'
import { Card, ErrorBox, Spinner, btnGhost, btnPrimary } from './ui'

const msg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const JPEG_TYPES = ['image/jpeg', 'image/png']

/** Step before the live check: one close-up photo with the eyes wide open. The server keeps only a face fingerprint and an iris pattern
 *  from it (never the photo) and compares them with the live video, so a different person, or a photo of a photo, can be spotted. */
export function PhotoStep({ sessionId, onAccepted }: { sessionId: string; onAccepted: (r: ReferenceResult) => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [cam, setCam] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<ReferenceResult | null>(null)

  const stopCam = () => { streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null; setCam(false) }
  useEffect(() => stopCam, [])
  const openCam = async () => {
    setErr(null)
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs HTTPS (or localhost). You can upload a photo instead.')
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
      streamRef.current = s; setCam(true)
      requestAnimationFrame(() => { if (videoRef.current) { videoRef.current.srcObject = s; void videoRef.current.play().catch(() => undefined) } })
    } catch (e) { setErr(msg(e)) }
  }
  const send = async (blob: Blob | null) => {
    if (!blob) { setErr('Could not read the photo. Try again.'); return }
    setBusy(true); setErr(null); setResult(null)
    try {
      const r = await service.uploadReferencePhoto(sessionId, blob)
      setResult(r)
      if (r.accepted) { stopCam(); onAccepted(r) }
    } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  const snap = async () => send(await captureFrameAt(videoRef.current, 1280, 0.92))
  const pick = async (f?: File) => {
    if (!f) return
    if (!JPEG_TYPES.includes(f.type)) { setErr('Please choose a JPEG or PNG photo.'); return }
    await send(f)
  }

  return (
    <Card className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-400/10 text-brand-300"><Eye className="h-5 w-5" /></span>
        <div><h2 className="font-medium text-white">Your starting photo</h2>
          <p className="mt-1 text-sm text-slate-400">Take or upload one clear photo of your face, close to the camera, with <b className="text-slate-200">your eyes wide open</b> and looking straight at the lens. No sunglasses, no hat, one person only, in good light. The photo itself is not stored: only a numeric fingerprint of your face and eyes is kept to compare with the live check.</p></div></div>

      {cam && (
        <div className="space-y-3">
          <div className="relative aspect-[4/3] overflow-hidden rounded-2xl border border-white/10 bg-black"><video ref={videoRef} muted playsInline className="h-full w-full object-cover" aria-label="Camera preview" /></div>
          <div className="flex flex-wrap gap-3"><button className={btnPrimary} disabled={busy} onClick={() => void snap()}>{busy ? <Spinner /> : <Camera className="h-4 w-4" />}Take the photo (eyes wide open)</button><button className={btnGhost} onClick={stopCam}>Cancel</button></div>
        </div>)}
      {!cam && !result?.accepted && (
        <div className="flex flex-wrap gap-3">
          <button className={btnPrimary} disabled={busy} onClick={() => void openCam()}><Camera className="h-4 w-4" />Use my camera</button>
          <label className={`${btnGhost} cursor-pointer`}>{busy ? <Spinner /> : <UploadCloud className="h-4 w-4" />}Upload a photo<input type="file" accept="image/jpeg,image/png" capture="user" className="sr-only" disabled={busy} onChange={(e) => void pick(e.target.files?.[0])} /></label>
        </div>)}

      {err && <ErrorBox message={err} />}
      {result && !result.accepted && (
        <div role="alert" className="rounded-xl border border-amber-400/30 bg-amber-400/[0.07] p-4 text-sm text-amber-100"><p className="font-medium">That photo cannot be used yet. Please fix this and try again:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">{(result.messages?.length ? result.messages : result.issues).map((m) => <li key={m}>{m}</li>)}</ul></div>)}
      {result?.accepted && (
        <div className="flex items-center gap-2 text-sm text-emerald-300"><CheckCircle2 className="h-4 w-4" />Photo accepted.{result.iris_check === 'low_detail' ? ' The eyes were small in the photo, so the eye scan may be skipped.' : ''}</div>)}
    </Card>
  )
}
