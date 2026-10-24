import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LogOut, ShieldCheck } from 'lucide-react'
import { env } from '../config/env'
import { useAuth } from '../features/auth/AuthContext'
import { Pill } from './ui'
import type { Role } from '../types'

const nav: Record<Role | 'anon', readonly (readonly [string, string])[]> = {
  anon: [['/', 'Home'], ['/login', 'Sign in']],
  customer: [['/dashboard', 'My dashboard'], ['/verify', 'Verify']],
  officer: [['/officer', 'Review console']],
}
export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const items = nav[user?.role ?? 'anon']
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2.5 text-lg font-semibold tracking-tight text-white">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-indigo shadow-glow"><ShieldCheck className="h-[18px] w-[18px] text-ink-950" /></span>
            Satyapan<span className="hidden text-sm font-normal text-slate-500 sm:inline">सत्यापन</span>
          </Link>
          <nav aria-label="Main" className="flex flex-wrap items-center gap-1 text-sm">
            {items.map(([to, label]) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `rounded-lg px-3 py-1.5 transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white'}`}>{label}</NavLink>)}
            {user && <>
              <span className="ml-2 flex items-center gap-2.5 border-l border-white/10 pl-3">
                <span className="grid h-7 w-7 place-items-center rounded-full bg-gradient-to-br from-ink-600 to-ink-700 text-xs font-semibold uppercase text-white">{user.username.slice(0, 1)}</span>
                <span className="hidden text-slate-300 sm:inline">{user.username}</span><Pill tone={user.role === 'officer' ? 'cyan' : 'slate'}>{user.role}</Pill>
              </span>
              <button onClick={() => { logout(); navigate('/login') }} className="ml-1 inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-slate-400 transition-colors hover:text-white"><LogOut className="h-4 w-4" />Sign out</button>
            </>}
          </nav>
        </div>
        {env.useMocks && <div className="bg-cyan-400/10 px-4 py-1 text-center text-xs text-cyan-200">Mock mode: all sessions, signals, accounts and verification results are simulated.</div>}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8"><Outlet /></main>
      <footer className="border-t border-white/[0.06] px-4 py-4 text-center text-xs text-slate-500">Satyapan assists human review and does not independently establish fraud. A person makes every decision.</footer>
    </div>
  )
}
