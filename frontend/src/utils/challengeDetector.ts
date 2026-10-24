import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import type { Challenge } from '../types'
export type Measured = Record<string, number | string | null>
let landmarker: Promise<FaceLandmarker> | null = null
function load(): Promise<FaceLandmarker> {
  landmarker ??= FilesetResolver.forVisionTasks('/mediapipe-wasm').then((f) =>
    FaceLandmarker.createFromOptions(f, { baseOptions: { modelAssetPath: '/models/face_landmarker.task' }, runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true }))
  landmarker.catch(() => { landmarker = null })
  return landmarker
}
/** A separate landmarker instance (no blendshapes) for the pulse sampler, so it never shares timestamps with challenge detection. */
export async function createLandmarker(): Promise<FaceLandmarker> {
  const f = await FilesetResolver.forVisionTasks('/mediapipe-wasm')
  return FaceLandmarker.createFromOptions(f, { baseOptions: { modelAssetPath: '/models/face_landmarker.task' }, runningMode: 'VIDEO', numFaces: 1 })
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const median = (a: number[]) => { const b = [...a].sort((x, y) => x - y), m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2 }
const round1 = (n: number) => Math.round(n * 10) / 10
const TURN_DEG = 18 // stop early once the turn is clearly done (the server accepts 15 or more)
const TURN_MIN = 15 // same as the server's minimum, used to decide which direction to report
const BASELINE_FRAMES = 6 // frames used to learn how the head is held before the turn
const BUDGET_MS = 15000 // time allowed for a head turn or two blinks
const LISTEN_MS = 15000 // time allowed to say the phrase
const BLINK_CLOSE = 0.35, BLINK_OPEN = 0.2 // eyeBlink blendshape score (0 open .. 1 closed) to count a closure / reopening
/** Approximate head yaw in degrees from where the nose sits between the cheek edges. Positive = turned toward the USER'S right.
 *  Heuristic (not calibrated): the video preview must stay un-mirrored for the sign to be right. */
function yawOf(l: { x: number }[]): number {
  const a = l[234].x, b = l[454].x, lo = Math.min(a, b), hi = Math.max(a, b)
  return (0.5 - (l[1].x - lo) / Math.max(hi - lo, 1e-6)) * 140
}
interface Recognizer { lang: string; interimResults: boolean; continuous: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onerror: (() => void) | null; onend: (() => void) | null; start(): void; stop(): void; abort(): void }
function listen(live: (s: string) => void, signal: AbortSignal): Promise<Measured> {
  const w = window as unknown as { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer }
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) { live('This browser has no speech recognition, so this result will be unavailable. Try Chrome or Safari.'); return Promise.resolve({}) }
  return new Promise((resolve) => {
    // The challenge words are Indian names, so recognise with the Indian-English model. Chrome ends a session after a
    // short silence, so restart it until the time budget is used; a single session often heard nothing at all.
    const end = Date.now() + LISTEN_MS
    let text = '', finished = false, quiet: ReturnType<typeof setTimeout> | undefined, r: Recognizer | null = null
    const done = () => { if (finished) return; finished = true; clearTimeout(quiet); clearTimeout(hard); try { r?.abort() } catch { /* already stopped */ } resolve(text.trim() ? { spoken_text: text.trim() } : {}) }
    const hard = setTimeout(done, LISTEN_MS)
    signal.addEventListener('abort', () => { text = ''; done() })
    const begin = () => {
      if (finished) return
      r = new Ctor()
      r.lang = 'en-IN'; r.interimResults = true; r.continuous = true
      const before = text
      r.onresult = (e) => {
        text = (before + ' ' + Array.from(e.results).map((x) => x[0].transcript).join(' ')).trim()
        live(`Heard: "${text}"`)
        clearTimeout(quiet)
        if (text.split(/\s+/).length >= 3) quiet = setTimeout(done, 1800) // three or more words, then a pause: finished
      }
      r.onerror = () => { /* onend follows; it decides whether to restart */ }
      r.onend = () => { if (!finished && Date.now() < end - 500) setTimeout(begin, 150); else done() }
      try { r.start() } catch { setTimeout(begin, 300) }
    }
    live('Listening... say the three words now, clearly.')
    begin()
  })
}
/** Measures one challenge in the browser. Returns {} when nothing could be measured (reported as "unavailable").
 *  Head turns are measured relative to where the head started, and the turn in the REQUESTED direction is reported,
 *  so a small twitch the other way before the real turn cannot make a correct turn fail. */
export async function measure(c: Challenge, video: HTMLVideoElement, live: (s: string) => void, signal: AbortSignal): Promise<Measured> {
  if (c.prompt.startsWith('Say aloud')) return listen(live, signal)
  live('Loading face detection...')
  const lm = await load()
  const blink = c.type === 'blink', left = c.prompt.toLowerCase().includes('left')
  const end = Date.now() + BUDGET_MS
  let seen = false, blinks = 0, closed = false, lo = 0, hi = 0, lastT = -1
  const base: number[] = [], eyes: number[] = []
  while (Date.now() < end && !signal.aborted) {
    if (video.readyState >= 2 && video.currentTime !== lastT) { // only analyse a new video frame
      lastT = video.currentTime
      const r = lm.detectForVideo(video, performance.now()), pts = r.faceLandmarks[0]
      if (pts) {
        seen = true
        if (blink) {
          const s = r.faceBlendshapes?.[0]?.categories ?? []
          const v = ((s.find((x) => x.categoryName === 'eyeBlinkLeft')?.score ?? 0) + (s.find((x) => x.categoryName === 'eyeBlinkRight')?.score ?? 0)) / 2
          // Learn this person's open-eye level first, so thick glasses or narrow eyes do not hide a blink.
          if (eyes.length < 8) eyes.push(v)
          const open = eyes.length >= 8 ? median(eyes) : 0
          if (!closed && v > Math.max(BLINK_CLOSE, open + 0.18)) { closed = true; blinks++ } else if (closed && v < Math.max(BLINK_OPEN, open + 0.08)) closed = false
          live(blinks ? `Blinks detected: ${blinks}` : 'Look at the camera and blink slowly and clearly, twice.')
          if (blinks >= 2) break
        } else {
          const raw = yawOf(pts)
          if (base.length < BASELINE_FRAMES) { base.push(raw); live('Look at the camera, then turn your head...') }
          else {
            const y = raw - median(base)
            lo = Math.min(lo, y); hi = Math.max(hi, y)
            live(`Head turn estimate: ${Math.round(y)} degrees (positive = your right)`)
            if (left ? y <= -TURN_DEG : y >= TURN_DEG) break
          }
        }
      } else live('No face detected. Face the camera in good light.')
    }
    await sleep(10)
  }
  if (signal.aborted || !seen) return {}
  if (blink) return { blink_count: blinks }
  if (base.length < BASELINE_FRAMES) return {} // face was visible too briefly to measure
  const want = left ? lo : hi, other = left ? hi : lo
  // Report the requested direction. Only if it fell short, report the larger opposite turn so the report can say so.
  const yaw = Math.abs(want) >= TURN_MIN || Math.abs(want) >= Math.abs(other) ? want : other
  return { head_yaw_deg: round1(yaw), head_yaw_min: round1(lo), head_yaw_max: round1(hi) }
}

const EYE_DIST_OK = 0.22 // share of the picture width between the outer eye corners; the server needs 0.20 or more
/** Guides the customer through the close-up eye scan: waits until the face is close enough and the eyes are open, and holds still for
 *  about a second. Returns true when that was reached (the caller then takes the close-up frames) and false on timeout. The server
 *  makes the real decision from the frames; this only helps the person get into position. */
export async function guideEyeScan(video: HTMLVideoElement, live: (s: string) => void, signal: AbortSignal, timeoutMs = 25000): Promise<boolean> {
  live('Loading face detection...')
  const lm = await load()
  const end = Date.now() + timeoutMs
  let good = 0, lastT = -1
  while (Date.now() < end && !signal.aborted) {
    if (video.readyState >= 2 && video.currentTime !== lastT) {
      lastT = video.currentTime
      const r = lm.detectForVideo(video, performance.now()), pts = r.faceLandmarks[0]
      if (!pts) { good = 0; live('No face detected. Face the camera.') }
      else {
        const dist = Math.abs(pts[33].x - pts[263].x)
        const s = r.faceBlendshapes?.[0]?.categories ?? []
        const blink = ((s.find((x) => x.categoryName === 'eyeBlinkLeft')?.score ?? 0) + (s.find((x) => x.categoryName === 'eyeBlinkRight')?.score ?? 0)) / 2
        if (dist < EYE_DIST_OK) { good = 0; live('Move closer to the camera...') }
        else if (blink > 0.3) { good = 0; live('Open your eyes wide...') }
        else { good++; live('Hold still...') }
        if (good >= 8) return true
      }
    }
    await sleep(25)
  }
  return false
}
