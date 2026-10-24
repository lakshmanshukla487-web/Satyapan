import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { Check, LogIn, ShieldCheck } from 'lucide-react'
import { useAuth } from '../features/auth/AuthContext'
import { DEMO_ACCOUNTS, homeFor } from '../features/auth/authService'
import { Card, ErrorBox, SimBanner, btnPrimary } from '../components/ui'
import { env } from '../config/env'

export const field = 'mt-1 w-full rounded-lg border border-white/10 bg-ink-950/70 px-3 py-2 text-sm text-white placeholder:text-slate-600 transition-colors focus:border-brand-400/60'

export default function LoginPage() {
  const { user, login } = useAuth()
  const from = (useLocation().state as { from?: string } | null)?.from
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to={from ?? homeFor(user.role)} replace />  // the route guard bounces a wrong-role target to the right dashboard
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try { await login(username.trim(), password) } catch (x) { setErr(x instanceof Error ? x.message : 'Sign-in failed.') } finally { setBusy(false) }
  }
  return (
    <div className="mx-auto grid max-w-5xl items-stretch gap-6 md:grid-cols-2">
      <aside className="relative hidden overflow-hidden rounded-3xl border border-white/[0.07] bg-gradient-to-br from-ink-800 to-ink-950 p-8 shadow-card md:block">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-brand-400/20 blur-3xl" />
        <div className="relative space-y-4">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-indigo shadow-glow"><ShieldCheck className="h-6 w-6 text-ink-950" /></span>
          <h2 className="text-2xl font-semibold text-white">Trusted video KYC, with a person in control.</h2>
          <ul className="space-y-3 text-sm text-slate-400">
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />Documents are checked before the camera starts.</li>
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />An officer approves every challenge you are asked to do.</li>
            <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />Video and audio are analysed, not stored.</li>
          </ul>
        </div>
      </aside>
      <div className="space-y-4 self-center">
        <h1 className="text-2xl font-semibold text-white">Sign in</h1>
        {env.useMocks && <SimBanner text={`Demo mode. ${DEMO_ACCOUNTS.map((a) => `${a.role}: ${a.username} / ${a.password}`).join('  |  ')}`} />}
        <Card>
          <form onSubmit={(e) => void submit(e)} className="space-y-4">
            <label className="block text-sm text-slate-300">Username<input className={field} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required /></label>
            <label className="block text-sm text-slate-300">Password<input className={field} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
            {err && <ErrorBox message={err} />}
            <button className={`${btnPrimary} w-full`} disabled={busy || !username || !password}><LogIn className="h-4 w-4" />{busy ? 'Signing in…' : 'Sign in'}</button>
          </form>
        </Card>
        <p className="text-sm text-slate-400">New customer? <Link to="/register" className="text-brand-300 underline">Create an account</Link>. Officer accounts are issued by an administrator.</p>
      </div>
    </div>
  )
}
