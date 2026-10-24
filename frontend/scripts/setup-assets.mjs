// Copies MediaPipe WASM files and downloads the face landmarker model into public/. Never fails the build.
import { cpSync, existsSync, mkdirSync, createWriteStream, renameSync } from 'node:fs'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
const wasm = 'node_modules/@mediapipe/tasks-vision/wasm'
if (existsSync(wasm)) cpSync(wasm, 'public/mediapipe-wasm', { recursive: true })
else console.warn('[assets] @mediapipe/tasks-vision not installed; run npm install.')
const model = 'public/models/face_landmarker.task'
const url = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
if (!existsSync(model)) {
  try {
    mkdirSync('public/models', { recursive: true })
    const r = await fetch(url)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    await pipeline(Readable.fromWeb(r.body), createWriteStream(model + '.part'))
    renameSync(model + '.part', model)
    console.log('[assets] downloaded face_landmarker.task')
  } catch (e) {
    console.warn(`[assets] Could not download face_landmarker.task (${e.message}). Save it from\n  ${url}\nto frontend/public/models/. Until then, challenge detection reports "unavailable".`)
  }
}
