import { useCallback, useEffect, useRef, useState } from 'react'

export type MediaState =
  | 'idle'
  | 'requesting'
  | 'active'
  | 'insecure'    // not a secure context (HTTP on a non-localhost LAN origin)
  | 'unsupported' // secure context but API is absent (very old browser)
  | 'denied'      // user or OS blocked the permission
  | 'no_device'   // no camera found, or constraints couldn't be satisfied
  | 'in_use'      // camera is held by another app
  | 'error'       // any other DOMException or unexpected throw

export function useMediaStream() {
  const streamRef = useRef<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [state, setState] = useState<MediaState>('idle')
  const [message, setMessage] = useState('')

  // Derived indicator: audio tracks are present
  const [micActive, setMicActive] = useState(false)

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setMicActive(false)
    setState('idle')
  }, [])

  /** Must only be called from a user action (button click). */
  const start = useCallback(async () => {
    // ── 1. Secure-context guard ───────────────────────────────────────────────
    // getUserMedia() is gated on secure contexts (HTTPS or localhost). On a plain
    // HTTP LAN URL navigator.mediaDevices is undefined – the browser will never
    // show a permission prompt. Report this clearly instead of saying "unsupported".
    if (!window.isSecureContext) {
      setState('insecure')
      setMessage(
        'Camera access requires HTTPS. ' +
        'Open this page over https:// (or http://localhost) instead of plain http://. ' +
        'See the README for certificate setup instructions.'
      )
      return
    }

    // ── 2. API availability guard ─────────────────────────────────────────────
    if (!navigator.mediaDevices?.getUserMedia) {
      setState('unsupported')
      setMessage(
        'Your browser does not support camera access. ' +
        'Use a current version of Chrome, Edge, Firefox, or Safari over HTTPS.'
      )
      return
    }

    setState('requesting')
    setMessage('')

    // ── 3. Request camera + microphone ────────────────────────────────────────
    // Try user-facing camera first (important on phones), fall back to any camera.
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' },
        audio: true,
      })
    } catch (firstErr) {
      // facingMode constraint can be over-constrained on desktop webcams;
      // retry without it before giving up.
      if (
        firstErr instanceof DOMException &&
        (firstErr.name === 'OverconstrainedError' || firstErr.name === 'ConstraintNotSatisfiedError')
      ) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        } catch (retryErr) {
          return handleError(retryErr)
        }
      } else {
        return handleError(firstErr)
      }
    }

    // ── 4. Attach stream to video element ─────────────────────────────────────
    streamRef.current = stream
    if (videoRef.current) {
      videoRef.current.srcObject = stream
      // play() can reject if the element is not yet visible; that is harmless.
      void videoRef.current.play().catch(() => undefined)
    }
    setMicActive(stream.getAudioTracks().length > 0)
    setState('active')

    function handleError(e: unknown) {
      const name = e instanceof DOMException ? e.name : ''
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setState('denied')
        setMessage(
          'Camera permission was denied. ' +
          "Allow camera and microphone in your browser's site settings, then click Retry. " +
          'On iOS, go to Settings \u2192 Safari \u2192 Camera.'
        )
      } else if (name === 'NotFoundError') {
        setState('no_device')
        setMessage('No camera was found on this device. Connect a camera and click Retry.')
      } else if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
        setState('no_device')
        setMessage('No camera matched the requested constraints. Connect a camera and click Retry.')
      } else if (name === 'NotReadableError' || name === 'AbortError') {
        setState('in_use')
        setMessage(
          'The camera could not be opened. It may be in use by another app. ' +
          'Close other apps using the camera and click Retry.'
        )
      } else {
        setState('error')
        setMessage(
          `Camera initialisation failed${e instanceof Error ? ': ' + e.message : ''}. ` +
          'Click Retry, or reload the page.'
        )
      }
    }
  }, [])

  // Stop all tracks when the component unmounts (navigating away from /verify).
  useEffect(() => stop, [stop])

  return { videoRef, streamRef, state, message, micActive, start, stop }
}
