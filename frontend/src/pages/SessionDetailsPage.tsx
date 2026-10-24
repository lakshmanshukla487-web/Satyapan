import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Ban, Download, FileText, Radio, ScrollText } from 'lucide-react'
import { service } from '../features/services'
import { useCall } from '../features/call/useCall'
import { useSession } from '../hooks/useSession'
import { useConnectionStatus } from '../hooks/useConnectionStatus'
import { Card, ErrorBox, Loading, Pill, SectionTitle, SimBanner, TierBadge, btnDanger, btnGhost, btnPrimary } from '../components/ui'
import { ApprovalPanel } from '../components/officer/ApprovalPanel'
import { FamiliesPanel } from '../components/officer/FamiliesPanel'
import { OfficerCallPanel } from '../components/CallPanels'
import { DocumentsPanel } from '../components/officer/DocumentsPanel'
import { TerminateDialog } from '../components/officer/TerminateDialog'
import { fmtTime } from '../utils/format'
import type { ChallengeStatus, DetectorSignal, ReasonSeverity, SignalStatus, WsEvent } from '../types'

const rTone: Record<ReasonSeverity, 'green' | 'red' | 'amber' | 'slate'> = { indicator: 'red', missing: 'amber', note: 'slate', ok: 'green' }
const rLabel: Record<ReasonSeverity, string> = { indicator: 'raised', missing: 'gap', note: 'note', ok: 'fine' }
const sTone: Record<SignalStatus, 'green' | 'red' | 'amber' | 'slate'> = { available: 'green', flagged: 'red', low_quality: 'amber', unavailable: 'slate', not_run: 'slate' }
const cTone: Record<ChallengeStatus, 'green' | 'red' | 'amber' | 'slate' | 'cyan'> = { passed: 'green', failed: 'red', in_progress: 'cyan', pending: 'slate', unavailable: 'amber', awaiting_approval: 'amber', done: 'slate' }
const cLabel = (s: ChallengeStatus) => (s === 'awaiting_approval' ? 'awaiting your approval' : s.replace('_', ' '))
const SUPPORTING = new Set(['pulse', 'provenance']) // never raise an indicator by themselves

function SignalCard({ s }: { s: DetectorSignal }) {
  return (
    <Card className="!p-4">
      <div className="flex items-start justify-between gap-2"><div><h3 className="font-medium text-white">{s.name}</h3><p className="text-xs text-slate-500">{s.model}{s.optional ? ' · optional' : ''}{SUPPORTING.has(s.id) ? ' · supporting only' : ''}</p></div><Pill tone={sTone[s.status]}>{s.status.replace('_', ' ')}</Pill></div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs"><div><dt className="text-slate-500">Score</dt><dd className="text-slate-200">{s.score === null ? 'Not available' : s.score.toFixed(2)}</dd></div><div><dt className="text-slate-500">Quality</dt><dd className="text-slate-200">{s.quality ?? 'Not assessed'}</dd></div><div><dt className="text-slate-500">Time</dt><dd className="text-slate-200">{fmtTime(s.timestamp)}</dd></div></dl>
      <p className="mt-3 text-sm text-slate-400">{s.explanation}</p>
    </Card>
  )
}

export default function SessionDetailsPage() {
  const { sessionId = '' } = useParams()
  const eventRef = useRef<(e: WsEvent) => void>(() => undefined)
  const { data: s, error, loading, reload, wsState, send } = useSession(sessionId, (e) => eventRef.current(e))
  const call = useCall('officer', send)
  eventRef.current = call.onEvent
  const conn = useConnectionStatus(wsState, Boolean(error))
  const [ending, setEnding] = useState(false)
  const [dlErr, setDlErr] = useState<string | null>(null)
  const download = async (f: 'pdf' | 'html' | 'json') => { setDlErr(null); try { await service.downloadReport(sessionId, f) } catch (e) { setDlErr(e instanceof Error ? e.message : 'Download failed.') } }
  if (loading && !s) return <Loading />
  if (error || !s) return <div className="space-y-4"><ErrorBox message={error ?? 'Session not found.'} onRetry={reload} /><Link className="text-brand-300 underline" to="/officer">Back to dashboard</Link></div>
  const live = s.backendStatus === 'running'
  const terminated = s.status === 'terminated'
  return (
    <div className="space-y-6">
      <Link to="/officer" className="inline-flex items-center gap-1 text-sm text-brand-300 hover:underline"><ArrowLeft className="h-4 w-4" />Back to console</Link>
      {s.simulated && <SimBanner text={`Simulated scenario: ${s.scenario}. Not produced by a real detector.`} />}
      {terminated && (
        <div role="status" className="flex items-start gap-3 rounded-xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200"><Ban className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">You ended this session.</p><p className="text-red-200/80">{s.terminationReason ? `Reason on record: ${s.terminationReason}` : 'No reason was recorded.'} The customer saw a neutral message. Evidence and the report are kept.</p></div></div>)}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="break-all font-mono text-xl font-semibold text-white">{s.id}</h1>
          <p className="mt-1 text-sm text-slate-400">{s.customer ? `${s.customer} · ` : ''}Started {fmtTime(s.startedAt)} · {s.status.replace('_', ' ')}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          {live && <Pill tone="cyan"><Radio className="h-3 w-3" />Live</Pill>}
          <Pill tone={conn.tone}>{conn.label}</Pill><TierBadge tier={s.tier} large />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link to={`/sessions/${s.id}/report`} className={btnPrimary}><FileText className="h-4 w-4" />Summary report</Link>
        <button className={btnGhost} onClick={() => void download('pdf')}><Download className="h-4 w-4" />Download PDF</button>
        <button className={btnGhost} onClick={() => void download('html')}>HTML</button>
        <button className={btnGhost} onClick={() => void download('json')}>JSON</button>
        <Link to={`/sessions/${s.id}/evidence`} className={btnGhost}><ScrollText className="h-4 w-4" />View evidence</Link>
        {live && <button className={`${btnDanger} ml-auto`} onClick={() => setEnding(true)}><Ban className="h-4 w-4" />End session now</button>}
      </div>
      {dlErr && <ErrorBox message={dlErr} />}
      <TerminateDialog open={ending} sessionId={s.id} onClose={() => setEnding(false)} onDone={reload} />

      <Card>
        <SectionTitle>Recommendation</SectionTitle>
        <p className="text-slate-200">{s.headline ?? s.recommendation}</p>
        {s.reasonDetails?.length ? <ul className="mt-3 space-y-2 text-sm">{s.reasonDetails.map((r, i) => <li key={`${r.code}-${i}`} className="flex items-start gap-2"><Pill tone={rTone[r.severity]}>{rLabel[r.severity]}</Pill><span className="text-slate-400"><span className="text-slate-200">{r.title}.</span> {r.detail}</span></li>)}</ul>
          : <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-400">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {s.nextSteps?.length ? <div className="mt-4 border-t border-white/[0.06] pt-3"><p className="text-xs uppercase tracking-wider text-slate-500">Suggested next steps</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">{s.nextSteps.map((n) => <li key={n}>{n}</li>)}</ul></div> : null}
        <p className="mt-3 text-xs text-slate-500">Scores are model outputs, not calibrated probabilities of fraud. A human reviewer makes the decision.</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <OfficerCallPanel call={call} running={live} />
        <ApprovalPanel sessionId={s.id} challenges={s.challenges} live={live} autoApprove={s.autoApprove} onChanged={reload} />
      </div>
      <FamiliesPanel families={s.families} coverage={s.coverage} missing={s.missingForGreen} overall={s.overallExplain} />
      <DocumentsPanel docs={s.documents} />

      <div><SectionTitle hint="Independent evidence families. Supporting families never raise an indicator on their own.">Signals</SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">{s.signals.map((x) => <SignalCard key={x.id} s={x} />)}</div></div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card><SectionTitle>Challenge history</SectionTitle>
          {s.challenges.length === 0 ? <p className="text-sm text-slate-500">No challenges yet.</p> : <ul className="space-y-2 text-sm">{s.challenges.map((c) => <li key={c.id} className="flex items-center justify-between gap-2"><span className="text-slate-300">{c.prompt || 'Hidden until approved'}</span><Pill tone={cTone[c.status]}>{cLabel(c.status)}</Pill></li>)}</ul>}</Card>
        <Card><SectionTitle>Session events</SectionTitle>
          <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1 text-sm">{s.events.map((e) => <li key={e.id} className="text-slate-400"><span className="text-xs text-slate-500">{fmtTime(e.timestamp)}</span> {e.message.replace(/[._]/g, ' ')}</li>)}</ol></Card>
      </div>
    </div>
  )
}
