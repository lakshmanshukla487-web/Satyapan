import { useEffect, useState } from 'react'
import { CheckCircle2, Clock, Hourglass, ListChecks, RefreshCw, Send, ShieldQuestion } from 'lucide-react'
import { service } from '../../features/services'
import type { Challenge, ChallengeKind, ChallengeStatus } from '../../types'
import { Card, ErrorBox, Pill, SectionTitle, Spinner, btnGhost, btnSuccess, inputCls } from '../ui'

export const KIND_LABEL: Record<ChallengeKind, string> = {
  head_left: 'Turn head left',
  head_right: 'Turn head right',
  blink: 'Blink twice',
  phrase: 'Say three words',
  eye_scan: 'Close-up eye scan',
}
const INSTRUCTIONS: Record<ChallengeKind, string> = {
  head_left: 'Watch the video: the head should turn clearly to the customer\'s left and come back.',
  head_right: 'Watch the video: the head should turn clearly to the customer\'s right and come back.',
  blink: 'Watch the eyes: two clear, natural blinks.',
  phrase: 'Listen: the customer should say the three words aloud, with lip movement matching the sound.',
  eye_scan: 'The customer moves close to the camera with eyes wide open; the server compares the iris with the start photo.',
}
const msg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const RESULT_TONE: Record<string, 'green' | 'red' | 'amber' | 'slate'> = { passed: 'green', failed: 'red', unavailable: 'amber' }
const VERIFY_TEXT: Record<string, string> = { server_confirmed: 'server confirmed', weak: 'partly confirmed', client_only: 'browser only', mismatch: 'browser contradicted', server_only: 'server decided' }
const statusLine = (c: Challenge): { text: string; tone: 'green' | 'red' | 'amber' | 'slate' | 'cyan' } => {
  const map: Record<ChallengeStatus, { text: string; tone: 'green' | 'red' | 'amber' | 'slate' | 'cyan' }> = {
    awaiting_approval: { text: 'waiting for you', tone: 'amber' }, in_progress: { text: 'with the customer', tone: 'cyan' }, unavailable: { text: c.approvalStatus === 'regenerated' ? 'replaced' : 'expired', tone: 'slate' },
    passed: { text: 'passed', tone: 'green' }, failed: { text: 'failed', tone: 'red' }, done: { text: 'answered', tone: 'slate' }, pending: { text: 'pending', tone: 'slate' },
  }
  return map[c.status]
}

/** Seconds until an ISO time, updated every second (null without a time). */
function useCountdown(iso?: string): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { if (!iso) return; const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t) }, [iso])
  return iso ? Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000)) : null
}

/** One challenge waiting for an officer. Its text is hidden from the customer until it is approved here. The ONE type selector
 *  starts at the generated type; whatever it shows is exactly what "Approve and send" releases to the customer. */
export function PendingChallenge({ sessionId, c, onDone }: { sessionId: string; c: Challenge; onDone: () => void }) {
  const [busy, setBusy] = useState<'approve' | 'regen' | null>(null)
  const [kind, setKind] = useState<ChallengeKind | ''>(c.kind ?? '')
  const [err, setErr] = useState<string | null>(null)
  const left = useCountdown(c.expiresAt)
  useEffect(() => setKind(c.kind ?? ''), [c.id, c.kind])  // a replaced challenge starts from its own type again
  const changed = Boolean(kind && kind !== c.kind)
  const run = async (what: 'approve' | 'regen') => {
    if (c.sessionId && c.sessionId !== sessionId) { setErr('This challenge belongs to a different session. Reload the page.'); return }  // never act across sessions
    setBusy(what); setErr(null)
    try {
      if (what === 'approve') await service.approveChallenge(sessionId, c.id, kind || undefined)
      else await service.regenerateChallenge(sessionId, c.id, kind || undefined)
      onDone()
    } catch (e) { setErr(msg(e)); onDone() } finally { setBusy(null) }
  }
  return (
    <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.07] p-4" data-challenge-id={c.id} data-session-id={sessionId}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-amber-300">Waiting for your approval{c.sequence ? ` · #${c.sequence}` : ''}</p>
          <p className={`mt-1 text-lg font-medium ${changed ? 'text-slate-500 line-through' : 'text-white'}`}>{c.prompt}</p>
          {changed && kind && <p className="mt-1 text-sm text-amber-200">Will be sent as: <span className="font-medium text-white">{KIND_LABEL[kind]}</span>{kind === 'phrase' ? ' (new random words)' : ''}</p>}
          {(changed ? kind : c.kind) && <p className="mt-1 text-xs text-slate-400">{INSTRUCTIONS[(changed ? kind : c.kind) as ChallengeKind]}</p>}
          <p className="mt-1 text-xs text-slate-500">The customer cannot see this yet.{left !== null ? ` The request expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}.` : ''}</p>
        </div>
        <Hourglass className="h-5 w-5 shrink-0 text-amber-300" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-slate-300">Challenge type
          <select aria-label="Challenge type to send" className={`${inputCls} !mt-0 !w-auto`} value={kind} disabled={busy !== null} onChange={(e) => setKind(e.target.value as ChallengeKind)}>
            {!c.kind && <option value="">As generated</option>}
            {(Object.keys(KIND_LABEL) as ChallengeKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}{k === c.kind ? ' (generated)' : ''}</option>)}
          </select></label>
        <button className={btnSuccess} disabled={busy !== null || left === 0} onClick={() => void run('approve')}>{busy === 'approve' ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}Approve and send</button>
        <button className={btnGhost} disabled={busy !== null || left === 0} onClick={() => void run('regen')} title="Discard this one and generate a new hidden challenge of the selected type, to look at before sending">{busy === 'regen' ? <Spinner /> : <RefreshCw className="h-4 w-4" />}Regenerate</button>
      </div>
      {left === 0 && <p className="mt-2 text-xs text-slate-400">This request expired; the customer's page asks for a new one automatically.</p>}
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
    </div>
  )
}

function CurrentChallenge({ c }: { c: Challenge }) {
  const left = useCountdown(c.expiresAt)
  return (
    <div className="rounded-xl border border-cyan-400/30 bg-cyan-400/[0.07] p-4" aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-cyan-300">With the customer now{c.sequence ? ` · #${c.sequence}` : ''}</p>
          <p className="mt-1 text-lg font-medium text-white">{c.prompt}</p>
          {c.kind && <p className="mt-1 text-xs text-slate-400">{INSTRUCTIONS[c.kind]}</p>}
        </div>
        <span className="inline-flex shrink-0 items-center gap-1 text-sm tabular-nums text-cyan-200"><Clock className="h-4 w-4" />{left !== null ? `${left}s` : '—'}</span>
      </div>
      {left === 0 && <p className="mt-2 text-xs text-slate-400">Time is up; an unanswered challenge counts as missed and the next one is requested.</p>}
    </div>
  )
}

/** The challenge side of the live workspace: what the customer is doing now, what waits for approval, the officer's controls and
 *  the history with results. All challenges shown belong to `sessionId` (the same session as the video next to it). */
export function ApprovalPanel({ sessionId, challenges, live, autoApprove = false, onChanged }: { sessionId: string; challenges: Challenge[]; live: boolean; autoApprove?: boolean; onChanged: () => void }) {
  const mine = challenges.filter((c) => !c.sessionId || c.sessionId === sessionId)
  const pending = mine.filter((c) => c.status === 'awaiting_approval')
  const current = [...mine].reverse().find((c) => c.status === 'in_progress')
  const history = [...mine].filter((c) => c.status !== 'awaiting_approval' && c.status !== 'in_progress').reverse()
  const [kind, setKind] = useState<ChallengeKind>('blink')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [auto, setAuto] = useState(autoApprove)
  useEffect(() => setAuto(autoApprove), [autoApprove])
  const counts = { passed: mine.filter((c) => c.status === 'passed').length, failed: mine.filter((c) => c.status === 'failed').length, missed: mine.filter((c) => c.status === 'unavailable' && c.approvalStatus !== 'regenerated').length }
  const toggleAuto = async (v: boolean) => {
    setAuto(v); setErr(null)
    try { await service.setAutoApprove(sessionId, v); onChanged() } catch (e) { setAuto(!v); setErr(msg(e)) }
  }
  const send = async () => {
    setBusy(true); setErr(null)
    try { await service.issueChallengeAsOfficer(sessionId, kind); onChanged() } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  return (
    <Card className="space-y-4">
      <SectionTitle hint="A generated challenge stays hidden from the customer until you release it." right={<Pill tone={pending.length ? 'amber' : 'slate'}>{pending.length} waiting</Pill>}>Challenges</SectionTitle>
      {live && (
        <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-300">
          <input type="checkbox" className="mt-1" checked={auto} onChange={(e) => void toggleAuto(e.target.checked)} />
          <span>Release every new challenge automatically for this session<span className="block text-xs text-slate-500">Challenges keep coming for the whole session. Leave this off to look at each one first.</span></span>
        </label>)}
      {!live && <p className="text-sm text-slate-400">The session is not live, so there is nothing to approve.</p>}
      {pending.map((c) => <PendingChallenge key={c.id} sessionId={sessionId} c={c} onDone={onChanged} />)}
      {live && current && <CurrentChallenge c={current} />}
      {live && !current && pending.length === 0 && (
        <p className="flex items-start gap-2 rounded-xl border border-white/[0.07] p-3 text-sm text-slate-400"><ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0" />No challenge is open. The next one appears here as soon as the customer's page requests it (a short pause follows each answer).</p>)}
      {live && pending.length === 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4">
          <span className="text-sm text-slate-400">Run a challenge now:</span>
          <select aria-label="Challenge type" className={`${inputCls} !mt-0 !w-auto`} value={kind} onChange={(e) => setKind(e.target.value as ChallengeKind)}>
            {(Object.keys(KIND_LABEL) as ChallengeKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
          <button className={btnGhost} disabled={busy} onClick={() => void send()}>{busy ? <Spinner /> : <Send className="h-4 w-4" />}Send to customer</button>
        </div>)}
      {err && <ErrorBox message={err} />}
      <div className="border-t border-white/[0.06] pt-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-500"><ListChecks className="h-3.5 w-3.5" />History</p>
          <span className="flex gap-1"><Pill tone="green">{counts.passed} passed</Pill><Pill tone={counts.failed ? 'red' : 'slate'}>{counts.failed} failed</Pill><Pill tone={counts.missed ? 'amber' : 'slate'}>{counts.missed} missed</Pill></span>
        </div>
        {history.length === 0 ? <p className="text-sm text-slate-500">No finished challenges yet.</p> : (
          <ul className="max-h-72 space-y-2 overflow-y-auto pr-1 text-sm">
            {history.map((c) => { const st = statusLine(c); return (
              <li key={c.id} className="rounded-lg border border-white/[0.06] p-2.5">
                <div className="flex items-start justify-between gap-2"><span className="text-slate-300">{c.sequence ? <span className="text-xs text-slate-500">#{c.sequence} </span> : null}{c.prompt || 'Hidden until approved'}</span>
                  <span className="flex shrink-0 gap-1">{c.result ? <Pill tone={RESULT_TONE[c.result] ?? 'slate'}>{c.result}</Pill> : <Pill tone={st.tone}>{st.text}</Pill>}{c.verification && c.result && <Pill tone={c.verification === 'mismatch' ? 'red' : c.verification === 'server_confirmed' ? 'green' : 'slate'}>{VERIFY_TEXT[c.verification] ?? c.verification}</Pill>}</span></div>
                {c.reason && <p className="mt-1 text-xs text-slate-500">{c.reason}</p>}
              </li>) })}
          </ul>)}
      </div>
    </Card>
  )
}
