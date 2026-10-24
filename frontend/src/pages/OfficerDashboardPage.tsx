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
import { fmtTime, signalCount } from '../utils/format'
import type { RiskTier, SessionStatus, VerificationSession } from '../types'

const filters: ('ALL' | RiskTier)[] = ['ALL', 'GREEN', 'AMBER', 'RED', 'GREY']
const statusLabel: Record<SessionStatus, { text: string; tone: 'cyan' | 'amber' | 'green' | 'slate' | 'red' }> = {
  in_progress: { text: 'In progress', tone: 'cyan' }, awaiting_review: { text: 'Awaiting review', tone: 'amber' }, reviewed: { text: 'Reviewed', tone: 'green' },
  abandoned: { text: 'Not completed', tone: 'slate' }, terminated: { text: 'Ended by officer', tone: 'red' },
}
const isLive = (s: VerificationSession) => s.backendStatus === 'running'
const docTone = { accepted: 'green', flagged: 'amber', needs_correction: 'red', not_submitted: 'slate' } as const

export default function OfficerDashboardPage() {
  const sessionsQ = useAsync(() => service.listSessions(), [])
  const pendingQ = useAsync(() => service.listPendingApprovals(), [])
  const requestsQ = useAsync(() => service.listPendingSessions(), [])
  const [q, setQ] = useState('')
  const [tier, setTier] = useState<'ALL' | RiskTier>('ALL')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { reload: reloadSessions } = sessionsQ, { reload: reloadPending } = pendingQ, { reload: reloadRequests } = requestsQ
  const reloadAll = useCallback(() => { reloadSessions(); reloadPending(); reloadRequests() }, [reloadSessions, reloadPending, reloadRequests])
  // The feed tells us something changed; reload once things settle instead of once per event.
  const feed = useOfficerFeed(() => { if (timer.current) clearTimeout(timer.current); timer.current = setTimeout(reloadAll, 500) })
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useEffect(() => { // an approval is time-limited, so keep the queue fresh even if the socket is down
    const t = setInterval(() => { reloadPending(); reloadRequests() }, feed === 'open' ? 20000 : 6000)
    return () => clearInterval(t)
  }, [feed, reloadPending, reloadRequests])

  const sessions = useMemo(() => sessionsQ.data ?? [], [sessionsQ.data])
  const pending = pendingQ.data ?? []
  const stats = useMemo(() => ({
    live: sessions.filter(isLive).length,
    awaiting: sessions.filter((s) => s.status === 'awaiting_review').length,
    flagged: sessions.filter((s) => s.tier === 'RED' || s.tier === 'AMBER').length,
    docs: sessions.filter((s) => s.documents && (s.documents.status === 'flagged' || s.documents.status === 'needs_correction')).length,
  }), [sessions])
  const rows = sessions.filter((s) => (tier === 'ALL' || s.tier === tier) && (s.id + (s.customer ?? '') + s.recommendation).toLowerCase().includes(q.toLowerCase()))
  const activity = useMemo(() => sessions.flatMap((s) => s.events.map((e) => ({ ...e, sid: s.id }))).sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 8), [sessions])
  const conn = useConnectionStatus(feed, Boolean(sessionsQ.error))
  const loading = sessionsQ.loading || pendingQ.loading

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-2xl font-semibold text-white">Review console</h1><p className="text-sm text-slate-400">Live sessions, approvals and risk, in one place.</p></div>
        <div className="flex items-center gap-3"><Pill tone={conn.tone}>{conn.label}</Pill><button className={btnGhost} onClick={reloadAll} disabled={loading}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button></div>
      </div>
      {sessionsQ.error && <ErrorBox message={sessionsQ.error} onRetry={reloadSessions} />}
      {pendingQ.error && <ErrorBox message={pendingQ.error} onRetry={reloadPending} />}

      <SessionRequests items={requestsQ.data ?? []} onChanged={reloadAll} />

      {/* Approval queue: challenges stay hidden from the customer until released here. */}
      {pending.length > 0 && (
        <Card className="border-amber-400/30">
          <SectionTitle hint="Each challenge is hidden from the customer until you approve it. Open the session to see their documents and live signals first." right={<Pill tone="amber"><BellRing className="h-3 w-3" />{pending.length} waiting</Pill>}>Approval queue</SectionTitle>
          <div className="grid gap-3 lg:grid-cols-2">
            {pending.map((p) => (
              <div key={p.challenge.id} className="space-y-2">
                <div className="flex items-center justify-between text-sm"><span className="text-slate-300">{p.customer ?? 'Customer'}</span><Link to={`/sessions/${p.sessionId}`} className="text-brand-300 underline">Open session</Link></div>
                <PendingChallenge sessionId={p.sessionId} c={p.challenge} onDone={reloadAll} />
              </div>))}
          </div>
        </Card>)}

      {sessionsQ.loading && !sessionsQ.data ? <Loading /> : sessionsQ.data && (<>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Live now" value={stats.live} tone={stats.live ? 'cyan' : 'slate'} hint={`${sessions.length} sessions in total`} />
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
                      <td className="p-2">{s.documents ? <Pill tone={docTone[s.documents.status]}>{s.documents.status.replace('_', ' ')}</Pill> : <span className="text-slate-600">—</span>}</td>
                      <td className="p-2"><TierBadge tier={s.tier} /></td>
                      <td className="p-2 text-slate-400">{signalCount(s)}/{s.signals.length}</td>
                    </tr>)
                })}</tbody></table></div>)}
          </Card>
          <Card>
            <SectionTitle right={<Activity className="h-4 w-4 text-slate-500" />}>Recent activity</SectionTitle>
            {activity.length === 0 ? <p className="text-sm text-slate-500">Nothing yet.</p> : <ul className="space-y-3 text-sm">{activity.map((a) => <li key={a.id} className="border-l border-white/10 pl-3"><Link to={`/sessions/${a.sid}`} className="font-mono text-xs text-brand-300">{a.sid.slice(0, 8)}…</Link> <span className="text-slate-300">{a.message.replace(/[._]/g, ' ')}</span><div className="text-xs text-slate-500">{fmtTime(a.timestamp)}</div></li>)}</ul>}
            <p className="mt-4 flex items-start gap-2 text-xs text-slate-500"><ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />Scores are model outputs, not calibrated probabilities. A person makes every decision.</p>
          </Card>
        </div></>)}
    </div>
  )
}
