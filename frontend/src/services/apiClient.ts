import { env } from '../config/env'
import { emitUnauthorized, getToken, setToken } from './tokenStore'

export class ApiError extends Error {
  constructor(message: string, public status: number | null, public code: string | null = null, public retryAfter: number | null = null, public requestId: string | null = null) { super(message) }
}

export interface ApiOptions {
  /** false for sign-in and sign-up: no token is sent and a 401 is just a wrong password, not an expired session. */
  auth?: boolean
  /** Automatic background traffic (frame/audio uploads, polling). While the server has asked us to slow down (HTTP 429 with
   *  Retry-After) these calls are not sent at all, so a throttled page does not keep hammering the server and does not fire a
   *  burst of queued requests when the limit lifts. User actions are always sent. */
  background?: boolean
  /** Extra attempts for transient failures (network error, 502/503/504, 429). Only for requests that are safe to repeat. */
  retries?: number
  /** Abort the request after this many milliseconds (default 30 s). */
  timeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 30_000
const MAX_RETRY_WAIT_MS = 15_000
let cooldownUntil = 0

/** Seconds left of a server-requested pause (0 = none). Pages use it to show "paused" instead of an error loop. */
export const cooldownRemaining = () => Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000))
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
/** Exponential backoff with full jitter: 0.5 s, 1 s, 2 s ... (capped), randomised so many clients do not retry in lockstep. */
export const backoffMs = (attempt: number, base = 500, cap = 8000) => Math.round(Math.random() * Math.min(cap, base * 2 ** attempt))

function parseRetryAfter(res: Response, body: { error?: { retry_after?: number } } | null): number | null {
  const h = res.headers.get('Retry-After')
  const n = h !== null && h.trim() !== '' ? Number(h) : body?.error?.retry_after
  return typeof n === 'number' && Number.isFinite(n) && n >= 0 ? Math.min(n, 3600) : null
}

/** 4xx answers that a repeat cannot fix (bad input, no permission, wrong state, workflow limits): never retried automatically. */
const isTransient = (e: ApiError) => e.status === null || e.status === 502 || e.status === 503 || e.status === 504 || (e.status === 429 && e.code === 'RATE_LIMITED')

async function once<T>(path: string, init: RequestInit | undefined, opts: ApiOptions): Promise<T> {
  const auth = opts.auth !== false
  const token = auth ? getToken() : null
  const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  const outer = init?.signal
  if (outer) { if (outer.aborted) ctrl.abort(); else outer.addEventListener('abort', () => ctrl.abort(), { once: true }) }
  let res: Response
  try {
    res = await fetch(env.apiBaseUrl + path, { ...init, signal: ctrl.signal, headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers } })
  } catch {
    clearTimeout(timer)
    if (outer?.aborted) throw new ApiError('The request was cancelled.', null, 'ABORTED')
    throw new ApiError(ctrl.signal.aborted ? 'The server took too long to answer. Please try again.' : 'Cannot reach the verification service. Check that the backend is running and the API URL is correct.', null, ctrl.signal.aborted ? 'TIMEOUT' : 'NETWORK')
  }
  clearTimeout(timer)
  if (!res.ok) {
    if (res.status === 401 && token) { setToken(null); emitUnauthorized() }  // session expired: send the user back to sign-in
    const b = (await res.json().catch(() => null)) as { error?: { message?: string; code?: string; request_id?: string | null; retry_after?: number } } | null
    const rid = b?.error?.request_id ?? res.headers.get('X-Request-ID')
    const retryAfter = parseRetryAfter(res, b)
    if (res.status === 429 && b?.error?.code === 'RATE_LIMITED') cooldownUntil = Math.max(cooldownUntil, Date.now() + (retryAfter ?? 5) * 1000)
    const fallback = res.status >= 500
      ? `The server could not process the request (HTTP ${res.status}) and gave no details. Check the terminal running the backend${rid ? ` (request ${rid})` : ''}.`
      : `Request failed (${res.status})`
    throw new ApiError(b?.error?.message ? (res.status >= 500 && rid ? `${b.error.message} (reference ${rid})` : b.error.message) : fallback, res.status, b?.error?.code ?? null, retryAfter, rid ?? null)
  }
  const type = res.headers.get('Content-Type') ?? ''
  return (type.includes('application/json') ? await res.json() : await res.text()) as T
}

export async function api<T>(path: string, init?: RequestInit, opts: ApiOptions = {}): Promise<T> {
  const retries = Math.max(0, opts.retries ?? 0)
  for (let attempt = 0; ; attempt++) {
    const left = cooldownRemaining()
    if (left > 0 && opts.background) throw new ApiError(`Paused for ${left} s because the server asked us to slow down.`, 429, 'CLIENT_COOLDOWN', left)
    try {
      return await once<T>(path, init, opts)
    } catch (e) {
      if (!(e instanceof ApiError) || attempt >= retries || !isTransient(e) || e.code === 'ABORTED') throw e
      const wait = e.retryAfter !== null ? e.retryAfter * 1000 : backoffMs(attempt)
      if (wait > MAX_RETRY_WAIT_MS) throw e  // a long pause is the user's decision, not a hidden wait
      await sleep(wait + backoffMs(0, 200, 200))
    }
  }
}
