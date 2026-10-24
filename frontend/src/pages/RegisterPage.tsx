import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { UserPlus } from 'lucide-react'
import { useAuth } from '../features/auth/AuthContext'
import { homeFor } from '../features/auth/authService'
import { Card, ErrorBox, btnPrimary } from '../components/ui'
import { field } from './LoginPage'

export default function RegisterPage() {
  const { user, register } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to={homeFor(user.role)} replace />
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(null)
    if (password !== again) return setErr('The two passwords do not match.')
    setBusy(true)
    try { await register(username.trim(), password) } catch (x) { setErr(x instanceof Error ? x.message : 'Could not create the account.') } finally { setBusy(false) }
  }
  return (
    <div className="mx-auto max-w-md space-y-4 pt-4">
      <h1 className="text-2xl font-semibold text-white">Create a customer account</h1>
      <Card>
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <label className="block text-sm text-slate-300">Username<input className={field} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" minLength={3} maxLength={30} pattern="[A-Za-z0-9_.\-]+" title="Letters, digits, dots, dashes and underscores" autoFocus required /></label>
          <label className="block text-sm text-slate-300">Password<input className={field} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={8} required /><span className="text-xs text-slate-500">At least 8 characters; not a common or all-numeric password.</span></label>
          <label className="block text-sm text-slate-300">Repeat password<input className={field} type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required /></label>
          {err && <ErrorBox message={err} />}
          <button className={`${btnPrimary} w-full`} disabled={busy || !username || !password}><UserPlus className="h-4 w-4" />{busy ? 'Creating…' : 'Create account'}</button>
        </form>
      </Card>
      <p className="text-sm text-slate-400">Already registered? <Link to="/login" className="text-brand-300 underline">Sign in</Link></p>
    </div>
  )
}
