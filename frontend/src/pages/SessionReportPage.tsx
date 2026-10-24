import { Link, useParams } from 'react-router-dom'
import { Download, Printer } from 'lucide-react'
import { service } from '../features/services'
import { useAsync } from '../hooks/useAsync'
import { useState } from 'react'
import { Card, ErrorBox, Loading, Pill, SimBanner, TierBadge, btnGhost, btnPrimary } from '../components/ui'
import { FamiliesPanel } from '../components/officer/FamiliesPanel'
import { fmtTime } from '../utils/format'
import type { Reason, ReasonSeverity, SessionReport } from '../types'

const GROUPS: { sev: ReasonSeverity; title: string; hint: string; tone: 'red' | 'amber' | 'slate' | 'green' }[] = [
  { sev: 'indicator', title: 'Raised concerns', hint: 'These are what set the colour.', tone: 'red' },
  { sev: 'missing', title: 'Evidence gaps', hint: 'Missing or unusable evidence. Never counted as suspicious.', tone: 'amber' },
  { sev: 'note', title: 'Notes', hint: 'Worth knowing, but did not change the colour.', tone: 'slate' },
  { sev: 'ok', title: 'Checks that looked fine', hint: 'Evidence consistent with authenticity (not a guarantee).', tone: 'green' },
]
const resultTone = (r: string) => (r === 'passed' ? 'green' : r === 'failed' ? 'red' : 'amber')
const score = (n: number | null) => (n === null ? 'n/a' : n.toFixed(2))
const mins = (s: number | null) => (s === null ? 'n/a' : s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`)

function ReasonList({ items, tone }: { items: Reason[]; tone: 'red' | 'amber' | 'slate' | 'green' }) {
  return <ul className="space-y-3">{items.map((r, i) => (
    <li key={`${r.code}-${i}`} className="rounded border border-white/[0.07] p-3">
      <div className="flex flex-wrap items-center gap-2"><Pill tone={tone}>{r.code}</Pill><span className="font-medium text-white">{r.title}</span></div>
      <p className="mt-1 text-sm text-slate-300">{r.detail}</p>
    </li>
  ))}</ul>
}

function download(r: SessionReport) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `satyapan-report-${r.session.id}.json` })
  a.click(); URL.revokeObjectURL(url)
}

export default function SessionReportPage() {
  const { sessionId = '' } = useParams()
  const { data: r, error, loading, reload } = useAsync(() => service.getReport(sessionId), [sessionId])
  const [dlErr, setDlErr] = useState<string | null>(null)
  const dl = async (f: 'pdf' | 'html' | 'json') => { setDlErr(null); try { await service.downloadReport(sessionId, f) } catch (e) { setDlErr(e instanceof Error ? e.message : 'Download failed.') } }
  if (loading) return <Loading />
  if (error || !r) return <div className="space-y-4"><ErrorBox message={error ?? 'Report not found.'} onRetry={reload} /><Link className="text-brand-300 underline" to="/officer">Back to dashboard</Link></div>
  const live = r.snapshot === 'generated_now'
  return (
    <div className="space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <Link to={`/sessions/${r.session.id}`} className="text-sm text-brand-300 underline">Back to session</Link>
        <div className="flex flex-wrap gap-2">
          {r.report_version === 'mock' ? <button className={btnGhost} onClick={() => download(r)}><Download className="h-4 w-4" />Download JSON</button> : <>
            <button className={btnPrimary} onClick={() => void dl('pdf')}><Download className="h-4 w-4" />Download PDF</button>
            <button className={btnGhost} onClick={() => void dl('html')}>HTML</button><button className={btnGhost} onClick={() => void dl('json')}>JSON</button></>}
          <button className={btnGhost} onClick={() => window.print()}><Printer className="h-4 w-4" />Print</button></div>
      </div>
      {dlErr && <ErrorBox message={dlErr} />}
      {r.report_version === 'mock' && <SimBanner text="Simulated report built from mock data. Nothing here came from a real detector." />}
      <div><h1 className="text-2xl font-semibold text-white">Session summary report</h1><p className="font-mono text-sm text-slate-400">{r.session.id}</p></div>
      {live && <p className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">Provisional: this session has not been completed, so this report was generated just now and may still change.</p>}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-3"><TierBadge tier={r.outcome.risk_level} /><span className="text-lg text-white">{r.outcome.headline}</span></div>
        <p className="text-slate-300">{r.outcome.summary}</p>
        <dl className="grid gap-3 text-sm sm:grid-cols-4">
          <div><dt className="text-slate-500">Rule applied</dt><dd className="text-slate-200">{r.outcome.rule}: {r.outcome.rule_text}</dd></div>
          <div><dt className="text-slate-500">Indicators raised</dt><dd className="text-slate-200">{r.outcome.indicators.length ? r.outcome.indicators.join(', ') : 'None'}</dd></div>
          <div><dt className="text-slate-500">Evidence completeness</dt><dd className="text-slate-200">{r.outcome.evidence_completeness}</dd></div>
          <div><dt className="text-slate-500">Policy</dt><dd className="text-slate-200">{r.session.policy_version}</dd></div>
        </dl>
        <p className="text-xs text-slate-500">A human officer makes the final decision. This report is decision support only.</p>
      </Card>

      <Card className="space-y-4">
        <h2 className="font-medium text-white">Why this colour</h2>
        {GROUPS.map((g) => { const items = r.reasons.filter((x) => x.severity === g.sev); return items.length === 0 ? null : (
          <div key={g.sev} className="space-y-2"><div><h3 className="text-sm font-medium text-slate-200">{g.title}</h3><p className="text-xs text-slate-500">{g.hint}</p></div><ReasonList items={items} tone={g.tone} /></div>) })}
      </Card>

      <FamiliesPanel families={r.families} coverage={null} missing={[]} overall={r.plain_language?.overall} />

      {r.session_analysis && (
        <Card className="space-y-2 text-sm">
          <h2 className="font-medium text-white">Over the length of the session</h2>
          <p className="text-slate-400">Ran for {mins(r.session_analysis.duration_seconds)}; median reaction time to a challenge {r.session_analysis.median_response_ms === null ? 'n/a' : `${(r.session_analysis.median_response_ms / 1000).toFixed(1)} s`}; {r.session_analysis.challenges_over_time.length} challenge{r.session_analysis.challenges_over_time.length === 1 ? '' : 's'} in total.</p>
          {r.session_analysis.challenges_over_time.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><thead className="text-xs text-slate-500"><tr><th className="p-2">At</th><th className="p-2">Type</th><th className="p-2">Result</th><th className="p-2">How well backed up</th><th className="p-2">Reaction</th></tr></thead>
            <tbody>{r.session_analysis.challenges_over_time.map((c) => <tr key={c.seq} className="border-t border-white/[0.07]"><td className="p-2 text-slate-400">{c.at_s}s</td><td className="p-2 text-slate-300">{c.type.replace('_', ' ')}</td><td className="p-2"><Pill tone={resultTone(c.result ?? c.status)}>{c.result ?? c.status}</Pill></td><td className="p-2 text-slate-400">{(c.verification ?? 'n/a').replace('_', ' ')}</td><td className="p-2 text-slate-400">{c.response_ms === null ? 'n/a' : `${(c.response_ms / 1000).toFixed(1)} s`}</td></tr>)}</tbody></table></div>}
        </Card>)}

      {r.identity && (
        <Card className="space-y-2 text-sm">
          <h2 className="font-medium text-white">Identity: start photo, face and iris</h2>
          <p className="text-slate-400">Start photo: {r.identity.reference_photo.uploaded ? 'uploaded' : 'not uploaded'}{r.identity.reference_photo.issues.length ? ` (notes: ${r.identity.reference_photo.issues.join(', ')})` : ''}. Usable iris pattern in the start photo: {r.identity.reference_photo.iris_usable ? 'yes' : 'no'}.</p>
          <p className="text-slate-400">Face match against the live video: {r.identity.face_match.samples} sample{r.identity.face_match.samples === 1 ? '' : 's'}; median similarity {score(r.identity.face_match.median_similarity)}, lowest {score(r.identity.face_match.min_similarity)} (needs about {score(r.identity.face_match.threshold)} or more).</p>
          {r.identity.iris_scans.length > 0 && <p className="text-slate-400">Iris scans: {r.identity.iris_scans.map((x) => `${x.verdict} (distance ${score(x.hamming_distance)})`).join('; ')}. This compares iris texture from ordinary camera images; it is not a retina scan.</p>}
        </Card>)}

      {r.network && (
        <Card className="space-y-2 text-sm">
          <h2 className="font-medium text-white">Network and camera</h2>
          <p className="text-slate-400">IP addresses seen: {r.network.ips_seen.length ? r.network.ips_seen.join(', ') : 'none recorded'}.</p>
          {r.network.notes.length > 0 && <ul className="list-disc space-y-1 pl-5 text-slate-400">{r.network.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        </Card>)}

      {r.documents && r.documents.documents.length > 0 && (
        <Card className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-medium text-white">KYC documents</h2><Pill tone={r.documents.status === 'accepted' ? 'green' : r.documents.status === 'flagged' ? 'amber' : 'slate'}>{r.documents.status.replace('_', ' ')}</Pill></div>
          {r.documents.findings.length > 0 && <ul className="space-y-2 text-sm">{r.documents.findings.map((f, i) => <li key={`${f.code}-${i}`} className="flex items-start gap-2"><Pill tone={f.severity === 'indicator' ? 'red' : f.severity === 'ok' ? 'green' : 'slate'}>{f.severity === 'indicator' ? 'raised' : f.severity}</Pill><span className="text-slate-400"><span className="text-slate-200">{f.title}.</span> {f.detail}</span></li>)}</ul>}
          {r.documents.missing.length > 0 && <p className="text-sm text-amber-300">Not provided: {r.documents.missing.join(', ')}</p>}
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="p-2">Document</th><th className="p-2">Number (masked)</th><th className="p-2">File</th><th className="p-2">OCR</th><th className="p-2">Problems</th></tr></thead>
            <tbody>{r.documents.documents.map((d) => <tr key={d.doc_type} className="border-t border-white/[0.07] align-top"><td className="p-2 text-slate-300">{d.doc_type.replace('_', ' ')}</td><td className="p-2 font-mono text-xs text-slate-400">{d.number_masked ?? 'n/a'}</td><td className="p-2 font-mono text-xs text-slate-500">{d.file_kind !== 'none' ? `${d.file_kind} · ${d.file_sha256?.slice(0, 10)}…` : 'none'}</td><td className="p-2 text-slate-400">{d.ocr_state ?? 'not run'}</td><td className="p-2 text-slate-400">{d.problems.length ? d.problems.join(', ') : 'none'}</td></tr>)}</tbody></table></div>
          <p className="text-xs text-slate-500">Structure, checksum and cross-document consistency only. This is not a lookup in UIDAI, NSDL or DigiLocker.</p>
        </Card>)}

      <Card><h2 className="mb-2 font-medium text-white">Suggested next steps for the officer</h2><ol className="list-decimal space-y-1 pl-5 text-sm text-slate-300">{r.next_steps.map((t) => <li key={t}>{t}</li>)}</ol></Card>

      <Card className="space-y-2">
        <h2 className="font-medium text-white">Challenge-response ({r.challenge_summary.passed} passed, {r.challenge_summary.failed} failed, {r.challenge_summary.unmeasured} not measured)</h2>
        {r.challenges.length === 0 ? <p className="text-sm text-slate-400">No challenges were issued.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="p-2">#</th><th className="p-2">Challenge</th><th className="p-2">Result</th><th className="p-2">Explanation</th><th className="p-2">Measured (client-reported)</th></tr></thead>
          <tbody>{r.challenges.map((c) => <tr key={c.number} className="border-t border-white/[0.07] align-top"><td className="p-2">{c.number}</td><td className="p-2 text-slate-300">{c.text}</td><td className="p-2"><Pill tone={resultTone(c.result)}>{c.result}</Pill></td><td className="p-2 text-slate-400">{c.reason ?? 'n/a'}</td><td className="p-2 font-mono text-xs text-slate-500">{Object.keys(c.measured).length ? JSON.stringify(c.measured) : 'none'}</td></tr>)}</tbody></table></div>}
      </Card>

      <Card className="space-y-2">
        <h2 className="font-medium text-white">Detectors</h2>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="p-2">Detector</th><th className="p-2">Status</th><th className="p-2">Samples (usable)</th><th className="p-2">Median score</th><th className="p-2">Highest</th><th className="p-2">Threshold</th><th className="p-2">Flagged</th></tr></thead>
          <tbody>{r.detectors.map((d) => <tr key={d.detector} className="border-t border-white/[0.07]"><td className="p-2 text-slate-300">{d.label}</td><td className="p-2">{d.status}{d.error_code ? <span className="text-xs text-slate-500"> ({d.error_code})</span> : null}</td><td className="p-2">{d.samples} ({d.usable_samples})</td><td className="p-2">{score(d.median_score)}</td><td className="p-2">{score(d.highest_score)}</td><td className="p-2">{score(d.threshold)}</td><td className="p-2">{d.flagged ? <Pill tone="red">yes</Pill> : 'no'}</td></tr>)}</tbody></table></div>
        <p className="text-xs text-slate-500">Scores are uncalibrated model outputs compared with demo thresholds, not probabilities of fraud. The median is taken over every sample in the session.</p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card><h2 className="mb-2 font-medium text-white">Timeline</h2><ol className="space-y-1 text-sm">{r.timeline.map((t, i) => <li key={i} className="text-slate-400"><span className="text-xs text-slate-500">{fmtTime(t.time)}</span> <span className="text-slate-200">{t.event}</span>{t.detail ? ` · ${t.detail}` : ''}</li>)}</ol></Card>
        <Card className="space-y-2 text-sm">
          <h2 className="font-medium text-white">Session and integrity</h2>
          <dl className="grid grid-cols-2 gap-2">
            <div><dt className="text-slate-500">Customer</dt><dd className="text-slate-200">{r.session.customer ?? 'n/a'}</dd></div>
            <div><dt className="text-slate-500">Duration</dt><dd className="text-slate-200">{mins(r.session.duration_seconds)}</dd></div>
            <div><dt className="text-slate-500">Started</dt><dd className="text-slate-200">{fmtTime(r.session.started_at)}</dd></div>
            <div><dt className="text-slate-500">Consent</dt><dd className="text-slate-200">{r.session.consent_given ? fmtTime(r.session.consent_timestamp) : 'not given'}</dd></div>
            <div><dt className="text-slate-500">Evidence chain</dt><dd className="text-slate-200">{r.evidence_integrity.chain_valid ? 'consistent' : 'MISMATCH'} ({r.evidence_integrity.events_checked} events)</dd></div>
            <div><dt className="text-slate-500">Report matches chain</dt><dd className="text-slate-200">{r.integrity.matches_evidence_chain === null ? 'not recorded yet' : r.integrity.matches_evidence_chain ? 'yes' : 'NO: report was changed'}</dd></div>
          </dl>
          <p className="break-all font-mono text-xs text-slate-500">SHA-256 {r.integrity.report_sha256}</p>
          <p className="text-xs text-slate-500">Report generated {fmtTime(r.generated_at)}.</p>
        </Card>
      </div>

      <Card><h2 className="mb-2 font-medium text-white">Limitations</h2><ul className="list-disc space-y-1 pl-5 text-sm text-slate-400">{r.limitations.map((t) => <li key={t}>{t}</li>)}</ul></Card>

      {r.plain_language && (
        <Card className="space-y-4 border-brand-400/30">
          <h2 className="text-lg font-semibold text-white">In plain words</h2>
          <p className="text-slate-200">{r.plain_language.overall}</p>
          <div><h3 className="text-sm font-medium text-slate-200">What the colours mean</h3>
            <ul className="mt-1 space-y-1 text-sm">{r.plain_language.colour_legend.map((c) => <li key={c.colour} className="text-slate-400"><b className="text-slate-200">{c.colour}</b>: {c.meaning}</li>)}</ul></div>
          <div><h3 className="text-sm font-medium text-slate-200">What each check found</h3>
            <ul className="mt-1 space-y-1 text-sm">{r.plain_language.by_check.map((c) => <li key={c.check} className="text-slate-400"><b className="text-slate-200">{c.check}</b> ({c.colour}): {c.in_plain_words}</li>)}</ul></div>
          <div><h3 className="text-sm font-medium text-slate-200">How this result was decided</h3><p className="mt-1 text-sm text-slate-400">{r.plain_language.how_decided}</p></div>
          <div><h3 className="text-sm font-medium text-slate-200">What to do now</h3><ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-slate-400">{r.plain_language.what_to_do.map((t) => <li key={t}>{t}</li>)}</ol></div>
        </Card>)}
    </div>
  )
}
