import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Ban, CheckCircle2, CircleSlash, Download, FileText, Radio, ScrollText, ShieldAlert, XCircle } from 'lucide-react'
import { service } from '../features/services'
import { useCall } from '../features/call/useCall'
import { useSession } from '../hooks/useSession'
import { useConnectionStatus } from '../hooks/useConnectionStatus'
import { Card, ErrorBox, Loading, Pill, SectionTitle, SimBanner, Spinner, TierBadge, btnDanger, btnGhost, btnPrimary } from '../components/ui'
import { ApprovalPanel } from '../components/officer/ApprovalPanel'
import { FamiliesPanel } from '../components/officer/FamiliesPanel'
import { OfficerCallPanel } from '../components/CallPanels'
import { DocumentsPanel } from '../components/officer/DocumentsPanel'
import { TerminateDialog } from '../components/officer/TerminateDialog'
import { fmtTime } from '../utils/format'
import type { DetectorSignal, ReasonSeverity, SignalStatus, VerificationSession, WsEvent } from '../types'

const rTone: Record<ReasonSeverity, 'green' | 'red' | 'amber' | 'slate'> = { indicator: 'red', missing: 'amber', note: 'slate', ok: 'green' }
const rLabel: Record<ReasonSeverity, string> = { indicator: 'raised', missing: 'gap', note: 'note', ok: 'fine' }
const sTone: Record<SignalStatus, 'green' | 'red' | 'amber' | 'slate'> = { available: 'green', flagged: 'red', low_quality: 'amber', unavailable: 'slate', not_run: 'slate' }
const SUPPORTING = new Set(['pulse', 'provenance']) // never raise an indicator by themselves
const docTone = { accepted: 'green', flagged: 'amber', needs_correction: 'red', not_submitted: 'slate' } as const

function SignalCard({ s }: { s: DetectorSignal }) {
  return (
    <Card className="!p-4">
      <div className="flex items-start justify-between gap-2"><div><h3 className="font-medium text-white">{s.name}</h3><p className="text-xs text-slate-500">{s.model}{s.optional ? ' · optional' : ''}{SUPPORTING.has(s.id) ? ' · supporting only' : ''}</p></div><Pill tone={sTone[s.status]}>{s.status.replace('_', ' ')}</Pill></div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs"><div><dt className="text-slate-500">Score</dt><dd className="text-slate-200">{s.score === null ? 'Not available' : s.score.toFixed(2)}</dd></div><div><dt className="text-slate-500">Quality</dt><dd className="text-slate-200">{s.quality ?? 'Not assessed'}</dd></div><div><dt className="text-slate-500">Time</dt><dd className="text-slate-200">{fmtTime(s.timestamp)}</dd></div></dl>
      <p className="mt-3 text-sm text-slate-400">{s.explanation}</p>
    </Card>
  )
}

/** Keeps three different things apart: real risk indicators, evidence that is simply missing (models unavailable, gaps), and
 *  challenges the customer failed. An unavailable model is never shown as suspicion. */
function SessionContext({ s }: { s: VerificationSession }) {
  const indicators = (s.reasonDetails ?? []).filter((r) => r.severity === 'indicator')
  const gaps = (s.reasonDetails ?? []).filter((r) => r.severity === 'missing')
  const unavailable = s.signals.filter((x) => x.status === 'unavailable' && !x.optional)
  const failed = s.challenges.filter((c) => c.status === 'failed')
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Card className="!p-4">
        <p className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-red-300"><ShieldAlert className="h-3.5 w-3.5" />Risk indicators raised</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-white">{indicators.length}</p>
        <ul className="mt-1 space-y-0.5 text-xs text-slate-400">{indicators.slice(0, 4).map((r, i) => <li key={`${r.code}-${i}`}>{r.title}</li>)}{indicators.length === 0 && <li>None so far.</li>}</ul>
      </Card>
      <Card className="!p-4">
        <p className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-300"><CircleSlash className="h-3.5 w-3.5" />Evidence missing (not suspicion)</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-white">{gaps.length + unavailable.length}</p>
        <ul className="mt-1 space-y-0.5 text-xs text-slate-400">
          {unavailable.slice(0, 3).map((x) => <li key={x.id}>{x.name}: model unavailable{x.explanation.startsWith('Reason code') ? ` (${x.explanation.replace('Reason code: ', '')})` : ''}</li>)}
          {gaps.slice(0, Math.max(0, 4 - unavailable.length)).map((r, i) => <li key={`${r.code}-${i}`}>{r.title}</li>)}
          {gaps.length + unavailable.length === 0 && <li>No gaps reported.</li>}
        </ul>
      </Card>
      <Card className="!p-4">
        <p className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-amber-300"><XCircle className="h-3.5 w-3.5" />Challenges failed</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-white">{failed.length}<span className="text-sm font-normal text-slate-500"> of {s.challenges.filter((c) => c.result).length} answered</span></p>
        <p className="mt-1 text-xs text-slate-400">A failed challenge is not proof of fraud: check the video and the reason in the history.</p>
      </Card>
    </div>
  )
}

export default function SessionDetailsPage() {
  const { sessionId = '' } = useParams()
  const eventRef = useRef<(e: WsEvent) => void>(() => undefined)
  const { data: s, error, loading, reload, refresh, wsState, send } = useSession(sessionId, (e) => eventRef.current(e))
  const call = useCall('officer', send)
  eventRef.current = call.onEvent
  const conn = useConnectionStatus(wsState, Boolean(error) && !s)
  const [ending, setEnding] = useState(false)
  const [dlErr, setDlErr] = useState<string | null>(null)
  const [confirmFinish, setConfirmFinish] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [finishErr, setFinishErr] = useState<string | null>(null)
  const finish = async () => {
    setFinishing(true); setFinishErr(null)
    try { call.hangUp(); await service.finishSession(sessionId); setConfirmFinish(false); reload() }
    catch (e) { setFinishErr(e instanceof Error ? e.message : 'Could not finish the session.') } finally { setFinishing(false) }
  }
  const download = async (f: 'pdf' | 'html' | 'json') => { setDlErr(null); try { await service.downloadReport(sessionId, f) } catch (e) { setDlErr(e instanceof Error ? e.message : 'Download failed.') } }
  if (loading && !s) return <Loading />
  if (!s) return <div className="space-y-4"><ErrorBox message={error ?? 'Session not found.'} onRetry={() => window.location.reload()} /><Link className="text-brand-300 underline" to="/officer">Back to dashboard</Link></div>
  const live = s.backendStatus === 'running'
  const terminated = s.status === 'terminated'
  return (
    <div className="space-y-6">
      <Link to="/officer" className="inline-flex items-center gap-1 text-sm text-brand-300 hover:underline"><ArrowLeft className="h-4 w-4" />Back to console</Link>
      {s.simulated && <SimBanner text={`Simulated scenario: ${s.scenario}. Not produced by a real detector.`} />}
      {terminated && (
        <div role="status" className="flex items-start gap-3 rounded-xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-200"><Ban className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">This session was ended by an officer.</p><p className="text-red-200/80">{s.terminationReason ? `Reason on record: ${s.terminationReason}` : 'No reason was recorded.'} The customer saw a neutral message. Evidence and the report are kept.</p></div></div>)}
      {error && <p role="status" className="flex items-center gap-2 text-xs text-amber-300"><AlertTriangle className="h-3.5 w-3.5" />Could not refresh just now ({error}). The page keeps the last data and updates again automatically.</p>}

      {/* Session context: identifier, state, documents and risk at a glance. */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">Live verification workspace</p>
          <h1 className="break-all font-mono text-xl font-semibold text-white">{s.id}</h1>
          <p className="mt-1 text-sm text-slate-400">{s.customer ? `${s.customer} · ` : ''}Started {fmtTime(s.startedAt)} · {s.backendStatus ?? s.status.replace('_', ' ')}{s.approval && s.approval !== 'not_required' ? ` · request ${s.approval}` : ''}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {live && <Pill tone="cyan"><Radio className="h-3 w-3" />Live</Pill>}
          {s.documents && <Pill tone={docTone[s.documents.status]}>documents {s.documents.status.replace('_', ' ')}</Pill>}
          <Pill tone={conn.tone}>{conn.label}</Pill><TierBadge tier={s.tier} large />
        </div>
      </div>

      {/* The workspace: the customer's live video and the challenges of the SAME session, side by side (stacked on small screens). */}
      <section aria-label="Live verification workspace" className="grid items-start gap-4 lg:grid-cols-5">
        <div className="lg:sticky lg:top-20 lg:col-span-3"><OfficerCallPanel call={call} running={live} sessionId={s.id} /></div>
        <div className="lg:col-span-2"><ApprovalPanel sessionId={s.id} challenges={s.challenges} live={live} autoApprove={s.autoApprove} onChanged={() => refresh(['challenges', 'core'])} /></div>
      </section>

      <SessionContext s={s} />

      <div className="flex flex-wrap gap-2">
        <Link to={`/sessions/${s.id}/report`} className={btnPrimary}><FileText className="h-4 w-4" />Summary report</Link>
        <button className={btnGhost} onClick={() => void download('pdf')}><Download className="h-4 w-4" />Download PDF</button>
        <button className={btnGhost} onClick={() => void download('html')}>HTML</button>
        <button className={btnGhost} onClick={() => void download('json')}>JSON</button>
        <Link to={`/sessions/${s.id}/evidence`} className={btnGhost}><ScrollText className="h-4 w-4" />View evidence</Link>
        {live && <div className="ml-auto flex flex-wrap gap-2">
          {!confirmFinish && <button className={btnPrimary} onClick={() => setConfirmFinish(true)}><CheckCircle2 className="h-4 w-4" />Finish verification</button>}
          {confirmFinish && <><button className={btnPrimary} disabled={finishing} onClick={() => void finish()}>{finishing ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}Confirm finish</button><button className={btnGhost} disabled={finishing} onClick={() => setConfirmFinish(false)}>Cancel</button></>}
          <button className={btnDanger} onClick={() => setEnding(true)}><Ban className="h-4 w-4" />End session now</button></div>}
      </div>
      {live && confirmFinish && <p className="text-xs text-slate-400">Finishing completes the live check and freezes the report; the customer's camera stops and they see that the verification was submitted. Sessions shorter than 90 seconds cannot be GREEN.</p>}
      {dlErr && <ErrorBox message={dlErr} />}
      {finishErr && <ErrorBox message={finishErr} />}
      <TerminateDialog open={ending} sessionId={s.id} onClose={() => setEnding(false)} onDone={reload} />

      <Card>
        <SectionTitle>Recommendation</SectionTitle>
        <p className="text-slate-200">{s.headline ?? s.recommendation}</p>
        {s.reasonDetails?.length ? <ul className="mt-3 space-y-2 text-sm">{s.reasonDetails.map((r, i) => <li key={`${r.code}-${i}`} className="flex items-start gap-2"><Pill tone={rTone[r.severity]}>{rLabel[r.severity]}</Pill><span className="text-slate-400"><span className="text-slate-200">{r.title}.</span> {r.detail}</span></li>)}</ul>
          : <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-400">{s.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {s.nextSteps?.length ? <div className="mt-4 border-t border-white/[0.06] pt-3"><p className="text-xs uppercase tracking-wider text-slate-500">Suggested next steps</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">{s.nextSteps.map((n) => <li key={n}>{n}</li>)}</ul></div> : null}
        <p className="mt-3 text-xs text-slate-500">Scores are model outputs, not calibrated probabilities of fraud. A human reviewer makes the decision.</p>
      </Card>
      <FamiliesPanel families={s.families} coverage={s.coverage} missing={s.missingForGreen} overall={s.overallExplain} />
      <DocumentsPanel docs={s.documents} />

      <div><SectionTitle hint="Independent evidence families. 'Unavailable' means the model is not installed or could not run; it is a gap, not a risk signal. Supporting families never raise an indicator on their own.">Signals</SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">{s.signals.map((x) => <SignalCard key={x.id} s={x} />)}</div></div>

      <Card><SectionTitle hint="Newest events of the hash-chained evidence log (the full chain is on the evidence page).">Session events</SectionTitle>
        <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1 text-sm">{[...s.events].reverse().map((e) => <li key={e.id} className="text-slate-400"><span className="text-xs text-slate-500">{fmtTime(e.timestamp)}</span> {e.message.replace(/[._]/g, ' ')}</li>)}</ol></Card>
    </div>
  )
}
