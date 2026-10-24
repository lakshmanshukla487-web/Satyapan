import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, BellRing, Radio, RefreshCw, Search, ShieldAlert } from 'lucide-react'
import { service } from '../features/services'
import { useAsync } from '../hooks/useAsync'
import { useOfficerFeed } from '../hooks/useOfficerFeed'
import { Card, Empty, ErrorBox, Loading, Pill, SectionTitle, Stat, TierBadge, btnGhost, inputCls } from '../components/ui'
import { PendingChallenge } from '../components/officer/ApprovalPanel'
import { SessionRequests } from '../components/officer/SessionRequests'
import { TierChart } from '../components/dashboard/TierChart'
import { useConnectionStatus } from '../hooks/useConnectionStatus'
import { fmtTime } from '../utils/format'
import type { DashboardSession, RiskTier, SessionStatus } from '../types'

const filters: ('ALL' | RiskTier)[] = ['ALL', 'GREEN', 'AMBER', 'RED', 'GREY']
const statusLabel: Record<SessionStatus, { text: string; tone: 'cyan' | 'amber' | 'green' | 'slate' | 'red' }> = {
  in_progress: { text: 'In progress', tone: 'cyan' }, awaiting_review: { text: 'Awaiting review', tone: 'amber' }, reviewed: { text: 'Reviewed', tone: 'green' },
  abandoned: { text: 'Not completed', tone: 'slate' }, terminated: { text: 'Ended by officer', tone: 'red' },
}
const isLive = (s: DashboardSession) => s.backendStatus === 'running'
const docTone = { accepted: 'green', flagged: 'amber', needs_correction: 'red', not_submitted: 'slate', not_checked: 'slate' } as const
const RELOAD_EVERY_MS = 5000      // feed events (one per upload of every live customer) refresh the console at most every 5 s
const SAFETY_POLL_OPEN_MS = 30000 // socket open: a slow safety refresh only (approvals are time-limited)
const POLL_CLOSED_MS = 8000       // socket down: bounded polling fallback

export default function OfficerDashboardPage() {
  // ONE request returns the sessions, the approval queue, the requests and the activity (it used to be 5 requests per session).
  const dash = useAsync(() => service.getOfficerDashboard({ background: true }), [])
  const [q, setQ] = useState('')
  const [tier, setTier] = useState<'ALL' | RiskTier>('ALL')
  const { reload } = dash
  const timer = useRef<number | undefined>(undefined)
  const lastReload = useRef(0)
  const throttledReload = useCallback(() => {  // leading + trailing throttle: coalesces bursts of feed events into one request
    if (timer.current !== undefined) return
    const wait = Math.max(0, RELOAD_EVERY_MS - (Date.now() - lastReload.current))
    timer.current = window.setTimeout(() => { timer.current = undefined; lastReload.current = Date.now(); reload() }, wait)
  }, [reload])
  const feed = useOfficerFeed(throttledReload)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    const t = window.setInterval(throttledReload, feed === 'open' ? SAFETY_POLL_OPEN_MS : POLL_CLOSED_MS)
    return () => window.clearInterval(t)
  }, [feed, throttledReload])
  const manualReload = () => { lastReload.current = Date.now(); reload() }

  const sessions = useMemo(() => dash.data?.sessions ?? [], [dash.data])
  const pending = dash.data?.pendingApprovals ?? []
  const stats = useMemo(() => ({
    live: sessions.filter(isLive).length,
    awaiting: sessions.filter((s) => s.status === 'awaiting_review').length,
    flagged: sessions.filter((s) => s.tier === 'RED' || s.tier === 'AMBER').length,
    docs: sessions.filter((s) => s.documentsStatus === 'flagged' || s.documentsStatus === 'needs_correction').length,
  }), [sessions])
  const rows = sessions.filter((s) => (tier === 'ALL' || s.tier === tier) && (s.id + (s.customer ?? '') + s.recommendation).toLowerCase().includes(q.toLowerCase()))
  const activity = dash.data?.activity ?? []
  const conn = useConnectionStatus(feed, Boolean(dash.error) && !dash.data)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold text-white">Review console</h1><p className="text-sm text-slate-400">Live sessions, approvals and risk, in one place.</p></div>
        <div className="flex items-center gap-3"><Pill tone={conn.tone}>{conn.label}</Pill><button className={btnGhost} onClick={manualReload} disabled={dash.refreshing}><RefreshCw className={`h-4 w-4 ${dash.refreshing ? 'animate-spin' : ''}`} />Refresh</button></div>
      </div>
      {dash.error && (dash.data
        ? <p role="status" className="text-xs text-amber-300">Could not refresh just now ({dash.error}). Showing the last data; it updates again automatically.</p>
        : <ErrorBox message={dash.error} onRetry={manualReload} />)}

      <SessionRequests items={dash.data?.pendingRequests ?? []} onChanged={manualReload} />

      {/* Approval queue: challenges stay hidden from the customer until released here. */}
      {pending.length > 0 && (
        <Card className="border-amber-400/30">
          <SectionTitle hint="Each challenge is hidden from the customer until you approve it. Open the session to see the customer live and their documents first." right={<Pill tone="amber"><BellRing className="h-3 w-3" />{pending.length} waiting</Pill>}>Approval queue</SectionTitle>
          <div className="grid gap-3 lg:grid-cols-2">
            {pending.map((p) => (
              <div key={p.challenge.id} className="space-y-2">
                <div className="flex items-center justify-between text-sm"><span className="text-slate-300">{p.customer ?? 'Customer'}</span><Link to={`/sessions/${p.sessionId}`} className="text-brand-300 underline">Open live workspace</Link></div>
                <PendingChallenge sessionId={p.sessionId} c={p.challenge} onDone={manualReload} />
              </div>))}
          </div>
        </Card>)}

      {dash.loading && !dash.data ? <Loading /> : dash.data && (<>
        {dash.data.simulated && <p className="text-xs text-cyan-300">Mock mode: simulated sessions.</p>}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Live now" value={stats.live} tone={stats.live ? 'cyan' : 'slate'} hint={`${dash.data.total} sessions in total${dash.data.total > sessions.length ? ` (newest ${sessions.length} shown)` : ''}`} />
          <Stat label="Awaiting review" value={stats.awaiting} tone={stats.awaiting ? 'amber' : 'slate'} />
          <Stat label="Flagged (amber or red)" value={stats.flagged} tone={stats.flagged ? 'red' : 'slate'} />
          <Stat label="Documents to check" value={stats.docs} tone={stats.docs ? 'amber' : 'slate'} hint="mismatch or correction needed" />
        </div>
        <TierChart sessions={sessions} />
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <div className="mb-3 flex flex-wrap gap-3">
              <label className="relative min-w-48 flex-1"><span className="sr-only">Search sessions</span><Search className="absolute left-3 top-3 h-4 w-4 text-slate-500" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by ID, customer or recommendation" className={`${inputCls} !mt-0 pl-9`} /></label>
              <div role="group" aria-label="Filter by risk" className="flex gap-1">{filters.map((f) => <button key={f} aria-pressed={tier === f} onClick={() => setTier(f)} className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${tier === f ? 'bg-brand-400 font-semibold text-ink-950' : 'border border-white/10 text-slate-300 hover:bg-white/5'}`}>{f === 'ALL' ? 'All' : f}</button>)}</div>
            </div>
            {rows.length === 0 ? <Empty title="No sessions match" hint={sessions.length ? 'Clear the search or filter.' : 'Sessions will appear here once customers verify.'} /> : (
              <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs uppercase tracking-wider text-slate-500"><tr><th className="p-2">Session</th><th className="p-2">Customer</th><th className="p-2">Started</th><th className="p-2">Status</th><th className="p-2">Docs</th><th className="p-2">Risk</th><th className="p-2">Signals</th></tr></thead>
                <tbody>{rows.map((s) => {
                  const st = statusLabel[s.status]
                  return (
                    <tr key={s.id} className="border-t border-white/[0.06] transition-colors hover:bg-white/[0.03]">
                      <td className="p-2"><Link className="font-mono text-xs text-brand-300 underline" to={`/sessions/${s.id}`}>{s.id.slice(0, 8)}…</Link></td>
                      <td className="p-2 text-slate-300">{s.customer ?? '—'}</td>
                      <td className="whitespace-nowrap p-2 text-slate-400">{fmtTime(s.startedAt)}</td>
                      <td className="p-2"><span className="flex flex-wrap gap-1">{isLive(s) && <Pill tone="cyan"><Radio className="h-3 w-3" />Live</Pill>}<Pill tone={st.tone}>{st.text}</Pill></span></td>
                      <td className="p-2"><Pill tone={docTone[s.documentsStatus]}>{s.documentsStatus.replace('_', ' ')}</Pill></td>
                      <td className="p-2"><TierBadge tier={s.tier} /></td>
                      <td className="p-2 text-slate-400">{s.signalsOk}/{s.signalsTotal}</td>
                    </tr>)
                })}</tbody></table></div>)}
          </Card>
          <Card>
            <SectionTitle right={<Activity className="h-4 w-4 text-slate-500" />}>Recent activity</SectionTitle>
            {activity.length === 0 ? <p className="text-sm text-slate-500">Nothing yet.</p> : <ul className="space-y-3 text-sm">{activity.map((a) => <li key={a.id} className="border-l border-white/10 pl-3"><Link to={`/sessions/${a.sessionId}`} className="font-mono text-xs text-brand-300">{a.sessionId.slice(0, 8)}…</Link> <span className="text-slate-300">{a.type.replace(/[._]/g, ' ')}</span><div className="text-xs text-slate-500">{fmtTime(a.timestamp)}</div></li>)}</ul>}
            <p className="mt-4 flex items-start gap-2 text-xs text-slate-500"><ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />Scores are model outputs, not calibrated probabilities. A person makes every decision.</p>
          </Card>
        </div></>)}
    </div>
  )
}
