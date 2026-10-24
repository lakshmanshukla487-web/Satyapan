/** Grab one JPEG frame from a playing <video>. The backend accepts JPEG/PNG only. */
export function captureFrame(video: HTMLVideoElement | null): Promise<Blob | null> {
  if (!video || !video.videoWidth) return Promise.resolve(null)
  const c = document.createElement('canvas')
  c.width = Math.min(video.videoWidth, 640)
  c.height = Math.round((c.width * video.videoHeight) / video.videoWidth)
  c.getContext('2d')?.drawImage(video, 0, 0, c.width, c.height)
  return new Promise((r) => c.toBlob(r, 'image/jpeg', 0.85))
}

/** Record mono 16-bit WAV (MediaRecorder gives WebM/Opus, which the backend rejects). Nothing is stored in the browser. */
export function recordWav(stream: MediaStream, seconds: number): Promise<Blob> {
  return new Promise((resolve) => {
    const ctx = new AudioContext()
    void ctx.resume().catch(() => undefined)  // a context created outside a click may start suspended and would record silence
    const chunks: Float32Array[] = []
    const src = ctx.createMediaStreamSource(new MediaStream(stream.getAudioTracks()))
    const proc = ctx.createScriptProcessor(4096, 1, 1)
    const mute = ctx.createGain()
    mute.gain.value = 0
    proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
    src.connect(proc); proc.connect(mute); mute.connect(ctx.destination)
    setTimeout(() => { proc.disconnect(); src.disconnect(); const rate = ctx.sampleRate; void ctx.close(); resolve(encodeWav(chunks, rate)) }, seconds * 1000)
  })
}

function encodeWav(chunks: Float32Array[], rate: number): Blob {
  const n = chunks.reduce((a, c) => a + c.length, 0)
  const v = new DataView(new ArrayBuffer(44 + n * 2))
  const w = (o: number, s: string) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)))
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true)
  let o = 44
  for (const c of chunks) for (const x of c) { v.setInt16(o, Math.max(-1, Math.min(1, x)) * 0x7fff, true); o += 2 }
  return new Blob([v], { type: 'audio/wav' })
}

/** One JPEG frame at a given maximum width (the eye scan wants more detail than the 640 px used for ordinary frames). */
export function captureFrameAt(video: HTMLVideoElement | null, maxWidth: number, quality = 0.9): Promise<Blob | null> {
  if (!video || !video.videoWidth) return Promise.resolve(null)
  const c = document.createElement('canvas')
  c.width = Math.min(video.videoWidth, maxWidth)
  c.height = Math.round((c.width * video.videoHeight) / video.videoWidth)
  c.getContext('2d')?.drawImage(video, 0, 0, c.width, c.height)
  return new Promise((r) => c.toBlob(r, 'image/jpeg', quality))
}

/** Records `seconds` of the camera as numbered JPEG frames (about 25 per second) together with each frame's time, and the microphone
 *  as WAV over the same period. This is what the lip-sync check needs (it compares mouth movement with the voice). Held in memory only. */
export async function recordAvClip(video: HTMLVideoElement, stream: MediaStream, seconds: number): Promise<{ frames: Blob[]; times: number[]; wav: Blob }> {
  const wavP = recordWav(stream, seconds + 0.2)
  const t0 = performance.now()
  const c = document.createElement('canvas')
  const w = Math.min(video.videoWidth || 640, 480)
  c.width = w; c.height = Math.round((w * (video.videoHeight || 480)) / (video.videoWidth || 640))
  const g = c.getContext('2d')
  const frames: Blob[] = [], times: number[] = []
  let last = -1
  while (performance.now() - t0 < seconds * 1000 && frames.length < 90) {
    if (video.readyState >= 2 && video.currentTime !== last && g) {
      last = video.currentTime
      g.drawImage(video, 0, 0, c.width, c.height)
      const t = (performance.now() - t0) / 1000
      const b = await new Promise<Blob | null>((r) => c.toBlob(r, 'image/jpeg', 0.7))
      if (b) { frames.push(b); times.push(Math.round(t * 1000) / 1000) }
    }
    await new Promise((r) => setTimeout(r, 30))
  }
  return { frames, times, wav: await wavP }
}
