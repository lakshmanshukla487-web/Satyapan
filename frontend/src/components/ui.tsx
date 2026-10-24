import { useEffect, type ReactNode } from 'react'
import { AlertTriangle, Inbox, Loader2, X } from 'lucide-react'
import type { RiskTier } from '../types'

/* ------------------------------------------------------------------ risk tier */
export const tierStyle: Record<RiskTier, string> = {
  GREEN: 'bg-emerald-500/10 text-emerald-300 border-emerald-400/30',
  AMBER: 'bg-amber-500/10 text-amber-300 border-amber-400/30',
  RED: 'bg-red-500/10 text-red-300 border-red-400/30',
  GREY: 'bg-slate-500/10 text-slate-300 border-slate-400/30',
}
const tierDot: Record<RiskTier, string> = { GREEN: 'bg-emerald-400', AMBER: 'bg-amber-400', RED: 'bg-red-400', GREY: 'bg-slate-400' }
export const TierBadge = ({ tier, large = false }: { tier: RiskTier; large?: boolean }) => (
  <span className={`inline-flex items-center gap-2 rounded-full border font-semibold tracking-wide ${large ? 'px-4 py-1.5 text-sm' : 'px-2.5 py-0.5 text-xs'} ${tierStyle[tier]}`}>
    <span className={`relative flex ${large ? 'h-2.5 w-2.5' : 'h-2 w-2'}`}>
      {tier === 'RED' && <span className={`absolute inline-flex h-full w-full animate-ring rounded-full ${tierDot[tier]}`} />}
      <span className={`relative inline-flex h-full w-full rounded-full ${tierDot[tier]}`} />
    </span>{tier}
  </span>
)

/* ------------------------------------------------------------------ small pieces */
type Tone = 'slate' | 'cyan' | 'red' | 'amber' | 'green'
export const Pill = ({ children, tone = 'slate' }: { children: ReactNode; tone?: Tone }) => {
  const t = {
    slate: 'text-slate-300 border-white/10 bg-white/5', cyan: 'text-cyan-300 border-cyan-400/30 bg-cyan-400/10', red: 'text-red-300 border-red-400/30 bg-red-400/10',
    amber: 'text-amber-300 border-amber-400/30 bg-amber-400/10', green: 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10',
  }[tone]
  return <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${t}`}>{children}</span>
}
export const Card = ({ children, className = '' }: { children: ReactNode; className?: string }) => (
  <section className={`rounded-2xl border border-white/[0.07] bg-gradient-to-b from-ink-800/80 to-ink-900/80 p-5 shadow-card backdrop-blur ${className}`}>{children}</section>
)
export const SectionTitle = ({ children, hint, right }: { children: ReactNode; hint?: string; right?: ReactNode }) => (
  <div className="mb-3 flex items-start justify-between gap-3"><div><h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">{children}</h2>{hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}</div>{right}</div>
)
export const Stat = ({ label, value, tone = 'slate', hint }: { label: string; value: ReactNode; tone?: Tone; hint?: string }) => {
  const c = { slate: 'text-white', cyan: 'text-cyan-300', red: 'text-red-300', amber: 'text-amber-300', green: 'text-emerald-300' }[tone]
  return <Card className="!p-4"><p className={`text-3xl font-semibold tabular-nums ${c}`}>{value}</p><p className="mt-1 text-sm text-slate-400">{label}</p>{hint && <p className="text-xs text-slate-500">{hint}</p>}</Card>
}
export const Spinner = ({ className = 'h-4 w-4' }: { className?: string }) => <Loader2 className={`animate-spin ${className}`} aria-hidden />
export const Loading = () => <div role="status" className="flex items-center gap-2 p-6 text-slate-400"><Spinner />Loading…</div>
export const ErrorBox = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div><p>{message}</p>{onRetry && <button onClick={onRetry} className="mt-2 underline">Try again</button>}</div></div>
)
export const Empty = ({ title, hint }: { title: string; hint?: string }) => <div className="flex flex-col items-center gap-2 p-10 text-center text-slate-400"><Inbox className="h-8 w-8" /><p className="font-medium text-slate-200">{title}</p>{hint && <p className="text-sm">{hint}</p>}</div>
export const SimBanner = ({ text }: { text: string }) => <div className="rounded-xl border border-cyan-400/25 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-200">{text}</div>

/* ------------------------------------------------------------------ buttons and inputs */
export const btn = 'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100'
export const btnPrimary = `${btn} bg-gradient-to-r from-brand-400 to-brand-500 text-ink-950 shadow-glow hover:brightness-110`
export const btnGhost = `${btn} border border-white/10 bg-white/[0.03] text-slate-200 hover:bg-white/[0.08]`
export const btnSuccess = `${btn} bg-emerald-500 text-ink-950 hover:bg-emerald-400`
export const btnDanger = `${btn} border border-red-400/40 bg-red-500/10 text-red-200 hover:bg-red-500/20`
export const inputCls = 'mt-1 w-full rounded-lg border border-white/10 bg-ink-950/70 px-3 py-2 text-sm text-white placeholder:text-slate-600 transition-colors focus:border-brand-400/60'

/* ------------------------------------------------------------------ modal (focus-trapped enough for a confirm box: Esc closes) */
export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-md animate-fadeUp rounded-2xl border border-white/10 bg-ink-900 p-5 shadow-card">
        <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold text-white">{title}</h2><button onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-400 hover:text-white"><X className="h-4 w-4" /></button></div>
        {children}
      </div>
    </div>
  )
}
