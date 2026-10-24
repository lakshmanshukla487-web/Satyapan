import type { IntegrityProbe } from '../types'
interface FrameMeta { captureTime?: number; receiveTime?: number; mediaTime?: number }
type VideoWithRvfc = HTMLVideoElement & { requestVideoFrameCallback?: (cb: (now: number, meta: FrameMeta) => void) => number }

/** Evidence family 1 (pipeline integrity): what the camera calls itself, what the track settings say, and how regular
 *  the frame timing is. Everything here is client-reported and can be spoofed; the server treats it as supporting
 *  evidence only, and only a virtual-camera NAME together with unnaturally regular timing counts as an indicator.
 *  Uses the camera's capture timestamps where the browser exposes them (screen-refresh timestamps would look regular
 *  on every machine). */
export async function collectProbe(stream: MediaStream, video: HTMLVideoElement, ms = 3500): Promise<IntegrityProbe> {
  const track = stream.getVideoTracks()[0]
  const st = track?.getSettings?.() ?? {}
  const intervals: number[] = []
  const v = video as VideoWithRvfc
  if (v.requestVideoFrameCallback) {
    await new Promise<void>((resolve) => {
      const end = performance.now() + ms
      let last = -1
      const tick = (now: number, meta: FrameMeta) => {
        const t = meta.captureTime ?? meta.receiveTime ?? (meta.mediaTime !== undefined ? meta.mediaTime * 1000 : now)
        if (last >= 0 && t > last) intervals.push(t - last)
        last = t
        if (performance.now() < end && intervals.length < 300) v.requestVideoFrameCallback?.(tick)
        else resolve()
      }
      v.requestVideoFrameCallback?.(tick)
      setTimeout(resolve, ms + 1500)  // never hang if frames stop arriving
    })
  }
  const [video_devices, webrtc_ips] = await Promise.all([listVideoDevices(), stunAddresses()])
  const caps = typeof track?.getCapabilities === 'function' ? Object.keys(track.getCapabilities()) : []
  return {
    camera_label: (track?.label ?? '').slice(0, 200), width: Math.round(st.width ?? 0), height: Math.round(st.height ?? 0),
    frame_rate: typeof st.frameRate === 'number' ? Math.round(st.frameRate * 10) / 10 : null,
    intervals_ms: intervals.slice(0, 400).map((x) => Math.round(x * 100) / 100), webdriver: Boolean(navigator.webdriver),
    capabilities: caps.slice(0, 60), video_devices, native_get_user_media: isNative(navigator.mediaDevices?.getUserMedia), native_enumerate_devices: isNative(navigator.mediaDevices?.enumerateDevices),
    device_id_present: Boolean(st.deviceId), webrtc_ips, timezone: safeTz(), tz_offset_min: -new Date().getTimezoneOffset(),
  }
}

/** True when the browser function is still the built-in one. Video-injection tools replace getUserMedia with a script function. null = could not tell. */
function isNative(fn: unknown): boolean | null {
  if (typeof fn !== 'function') return null
  try { return /\[native code\]/.test(Function.prototype.toString.call(fn)) } catch { return null }
}
const safeTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone.slice(0, 64) } catch { return '' } }
async function listVideoDevices(): Promise<{ label: string }[]> {
  try { return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput').slice(0, 12).map((d) => ({ label: d.label.slice(0, 200) })) } catch { return [] }
}
/** The public addresses the browser itself reports through STUN. If these differ from the address the server sees, a VPN or proxy is
 *  hiding the real connection. Private (.local / 192.168...) addresses are not sent. */
async function stunAddresses(ms = 2500): Promise<string[]> {
  if (typeof RTCPeerConnection === 'undefined') return []
  const found = new Set<string>()
  let pc: RTCPeerConnection | null = null
  try {
    pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] })
    pc.createDataChannel('probe')
    pc.onicecandidate = (e) => {
      const m = e.candidate?.candidate.match(/ (\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f:]{6,}) \d+ typ (?:srflx|prflx)/i)
      if (m) found.add(m[1])
    }
    await pc.setLocalDescription(await pc.createOffer())
    await new Promise<void>((r) => { const t = setTimeout(r, ms); pc!.onicegatheringstatechange = () => { if (pc?.iceGatheringState === 'complete') { clearTimeout(t); r() } } })
  } catch { /* blocked or unsupported: the server just has nothing to compare */ } finally { try { pc?.close() } catch { /* closed */ } }
  return [...found].slice(0, 10)
}
