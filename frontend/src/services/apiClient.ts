import { env } from '../config/env'
import { emitUnauthorized, getToken, setToken } from './tokenStore'
export class ApiError extends Error {
  constructor(message: string, public status: number | null, public code: string | null = null) { super(message) }
}
/** `opts.auth: false` is for sign-in and sign-up: no token is sent and a 401 is just a wrong password, not an expired session. */
export async function api<T>(path: string, init?: RequestInit, opts?: { auth?: boolean }): Promise<T> {
  const auth = opts?.auth !== false
  const token = auth ? getToken() : null
  const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData
  let res: Response
  try {
    res = await fetch(env.apiBaseUrl + path, { ...init, headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers } })
  } catch {
    throw new ApiError('Cannot reach the verification service. Check that the backend is running and the API URL is correct.', null)
  }
  if (!res.ok) {
    if (res.status === 401 && token) { setToken(null); emitUnauthorized() }  // session expired: send the user back to sign-in
    const b = (await res.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null
    const rid = (b?.error as { request_id?: string | null } | undefined)?.request_id ?? res.headers.get('X-Request-ID')
    const fallback = res.status >= 500
      ? `The server could not process the request (HTTP ${res.status}) and gave no details. Check the terminal running the backend${rid ? ` (request ${rid})` : ''}.`
      : `Request failed (${res.status})`
    throw new ApiError(b?.error?.message ? (res.status >= 500 && rid ? `${b.error.message} (reference ${rid})` : b.error.message) : fallback, res.status, b?.error?.code ?? null)
  }
  return (await res.json()) as T
}
