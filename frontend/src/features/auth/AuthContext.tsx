import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from '../../services/apiClient'
import { getToken, onUnauthorized, setToken } from '../../services/tokenStore'
import type { User } from '../../types'
import { authService } from './authService'

interface AuthValue {
  user: User | null
  ready: boolean  // false while a stored token is being checked
  login(username: string, password: string): Promise<User>
  register(username: string, password: string): Promise<User>
  logout(): void
}
const Ctx = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let alive = true
    if (!getToken()) setReady(true)
    else authService.me()
      .then((u) => { if (alive) setUser(u) })
      .catch((e: unknown) => { if (e instanceof ApiError && e.status === 401) setToken(null) })  // other errors (backend down): keep the token, show signed-out
      .finally(() => { if (alive) setReady(true) })
    const off = onUnauthorized(() => setUser(null))  // the API client saw an expired or revoked token
    return () => { alive = false; off() }
  }, [])
  const adopt = useCallback((r: { token: string; user: User }) => { setToken(r.token); setUser(r.user); return r.user }, [])
  const value = useMemo<AuthValue>(() => ({
    user, ready,
    login: async (u, p) => adopt(await authService.login(u, p)),
    register: async (u, p) => adopt(await authService.register(u, p)),
    // Clear the user first so pages unmount (and cancel any live capture while the token still works), then revoke the
    // token on the server (best effort) and drop it locally.
    logout: () => { setUser(null); window.setTimeout(() => { void authService.logout().catch(() => undefined).finally(() => setToken(null)) }, 0) },
  }), [user, ready, adopt])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside <AuthProvider>')
  return v
}
