import { env } from '../../config/env'
import { ApiError, api } from '../../services/apiClient'
import { endpoints as ep } from '../../services/endpoints'
import { getToken } from '../../services/tokenStore'
import type { Role, User } from '../../types'

export interface AuthResult { token: string; user: User }
export interface AuthService {
  login(username: string, password: string): Promise<AuthResult>
  register(username: string, password: string): Promise<AuthResult>
  me(): Promise<User>
  logout(): Promise<void>  // revokes every token of the user on the server
}
const wait = (ms = 300) => new Promise((r) => setTimeout(r, ms))
export const homeFor = (role: Role) => (role === 'officer' ? '/officer' : role === 'developer' ? '/developer' : '/dashboard')

const post = (path: string, username: string, password: string) =>
  api<AuthResult>(path, { method: 'POST', body: JSON.stringify({ username, password }) }, { auth: false })

const realAuth: AuthService = {
  login: (u, p) => post(ep.login, u, p),
  register: (u, p) => post(ep.register, u, p),
  me: () => api<User>(ep.me),
  async logout() { await api(ep.logout, { method: 'POST' }) },
}

/** Demo accounts for mock mode only. The real backend never has built-in credentials. */
export const DEMO_ACCOUNTS: { username: string; password: string; role: Role }[] = [
  { username: 'officer', password: 'officer-pass-123', role: 'officer' },
  { username: 'customer', password: 'customer-pass-123', role: 'customer' },
]
const mockResult = (username: string, role: Role): AuthResult => ({ token: `mock.${role}.${username}`, user: { id: username, username, role } })
const mockAuth: AuthService = {
  async login(u, p) {
    await wait()
    const a = DEMO_ACCOUNTS.find((x) => x.username === u.trim().toLowerCase() && x.password === p)
    if (!a) throw new ApiError('Invalid username or password.', 401)
    return mockResult(a.username, a.role)
  },
  async register(u, p) {
    await wait()
    if (u.trim().length < 3 || p.length < 8) throw new ApiError('Username needs 3+ characters and the password 8+.', 422)
    return mockResult(u.trim().toLowerCase(), 'customer')
  },
  async me() {
    const [, role, username] = (getToken() ?? '').split('.')
    if ((role !== 'customer' && role !== 'officer') || !username) throw new ApiError('Not signed in.', 401)
    return mockResult(username, role).user
  },
  async logout() { /* nothing to revoke in mock mode */ },
}
export const authService: AuthService = env.useMocks ? mockAuth : realAuth
