import { createLandmarker } from './challengeDetector'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
export interface PulseTrace { fps: number; rgb: number[][] }

/** Evidence family 5 (pulse): the mean R, G, B of three small skin patches (forehead and both cheeks) for every new video
 *  frame over `seconds`. Only these numbers leave the browser, never video. The server runs the POS algorithm on them.
 *  Supporting evidence only: a missing pulse can be plain bad light, and a good deepfake can inherit a pulse. */
export async function samplePulse(video: HTMLVideoElement, seconds: number, signal: AbortSignal): Promise<PulseTrace | null> {
  const lm = await createLandmarker().catch(() => null)
  if (!lm) return null
  try {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    const rgb: number[][] = []
    const t0 = performance.now()
    let lastT = -1
    while (performance.now() - t0 < seconds * 1000 && !signal.aborted && rgb.length < 2400) {
      if (video.readyState >= 2 && video.videoWidth && video.currentTime !== lastT) {
        lastT = video.currentTime
        canvas.width = 320
        canvas.height = Math.round((320 * video.videoHeight) / video.videoWidth)
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const pts = lm.detectForVideo(video, performance.now()).faceLandmarks[0]
        if (pts) {
          const fw = Math.abs(pts[454].x - pts[234].x)
          const patch = (cx: number, cy: number): number[] | null => {
            const w = Math.max(4, Math.round(fw * 0.12 * canvas.width))
            const x = Math.round(cx * canvas.width - w / 2), y = Math.round(cy * canvas.height - w / 2)
            if (x < 0 || y < 0 || x + w > canvas.width || y + w > canvas.height) return null
            const d = ctx.getImageData(x, y, w, w).data
            let r = 0, g = 0, b = 0
            for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2] }
            const n = d.length / 4
            return [r / n, g / n, b / n]
          }
          const parts = [patch(pts[10].x, pts[10].y + fw * 0.12), patch(pts[50].x, pts[50].y), patch(pts[280].x, pts[280].y)].filter((p): p is number[] => p !== null)
          if (parts.length) rgb.push([0, 1, 2].map((c) => parts.reduce((a, p) => a + p[c], 0) / parts.length))
        }
      }
      await sleep(25)
    }
    const elapsed = (performance.now() - t0) / 1000
    if (signal.aborted || rgb.length < 100 || elapsed <= 0) return null
    return { fps: Math.min(60, Math.max(5, Math.round((rgb.length / elapsed) * 10) / 10)), rgb: rgb.map((p) => p.map((x) => Math.round(x * 100) / 100)) }
  } finally {
    lm.close()
  }
}
