import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { service } from '../features/services'
import { useAsync } from '../hooks/useAsync'
import { Card, ErrorBox, Loading, Pill, SimBanner, btnGhost, btnPrimary } from '../components/ui'
import { fmtTime } from '../utils/format'
import type { EvidenceVerificationResult } from '../types'
const tone = { valid: 'green', invalid: 'red', unavailable: 'slate', error: 'amber' } as const
export default function EvidencePage() {
  const { sessionId = '' } = useParams()
  const { data: p, error, loading, reload } = useAsync(() => service.getEvidence(sessionId), [sessionId])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<EvidenceVerificationResult | null>(null)
  const exportJson = () => {
    if (!p) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(p.raw ?? p, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = `${p.mock ? 'MOCK-' : ''}evidence-${p.sessionId}.json`; a.click(); URL.revokeObjectURL(url)
  }
  const verify = async () => {
    if (!text.trim()) { setResult({ state: 'error', simulated: false, message: 'Paste evidence JSON or upload a file first.' }); return }
    setBusy(true)
    try { setResult(await service.verifyEvidence(text)) } catch (e) { setResult({ state: 'error', simulated: false, message: e instanceof Error ? e.message : 'Verification failed.' }) } finally { setBusy(false) }
  }
  const upload = async (f: File | undefined) => { if (f) setText(await f.text()) }
  if (loading) return <Loading />
  if (error || !p) return <div className="space-y-4"><ErrorBox message={error ?? 'Evidence not found.'} onRetry={reload} /><Link className="text-brand-300 underline" to="/officer">Back to dashboard</Link></div>
  return (
    <div className="space-y-6">
      <Link to={`/sessions/${p.sessionId}`} className="text-sm text-brand-300 underline">Back to session</Link>
      {p.mock && <SimBanner text="Mock evidence packet. Hashes are placeholders, not real SHA-256 digests, and verification below is simulated." />}
      <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-2xl font-semibold text-white">Evidence for {p.sessionId}</h1><button className={btnPrimary} onClick={exportJson}><Download className="h-4 w-4" />Export evidence JSON</button></div>
      <Card><dl className="grid gap-3 text-sm sm:grid-cols-4"><div><dt className="text-slate-500">Generated</dt><dd>{fmtTime(p.generatedAt)}</dd></div><div><dt className="text-slate-500">Algorithm</dt><dd>{p.hashAlgorithm}</dd></div><div><dt className="text-slate-500">Events</dt><dd>{p.events.length}</dd></div><div><dt className="text-slate-500">Hash chain</dt><dd>{p.chainStatus === 'present' ? 'Present, not verified' : 'Unavailable'}</dd></div></dl></Card>
      <Card><h2 className="mb-3 font-medium text-white">Event timeline</h2>
        <ol className="space-y-3">{p.events.map((e) => <li key={e.id} className="border-l-2 border-ink-600 pl-3 text-sm"><p className="text-slate-200">{e.message} <span className="text-xs text-slate-500">{fmtTime(e.timestamp)}</span></p><p className="break-all font-mono text-xs text-slate-500">hash: {e.hash ?? 'Not available'}</p><p className="break-all font-mono text-xs text-slate-500">prev: {e.prevHash ?? 'None (first event)'}</p></li>)}</ol></Card>
      <Card><h2 className="mb-2 font-medium text-white">Verify an evidence packet</h2>
        <label className="text-sm text-slate-400" htmlFor="ev">Paste evidence JSON</label>
        <textarea id="ev" value={text} onChange={(e) => setText(e.target.value)} rows={6} className="mt-1 w-full rounded-md border border-white/10 bg-ink-950/70 p-2 font-mono text-xs" />
        <div className="mt-3 flex flex-wrap items-center gap-3"><label className={`${btnGhost} cursor-pointer`}>Upload file<input type="file" accept="application/json,.json" className="sr-only" onChange={(e) => void upload(e.target.files?.[0])} /></label><button className={btnPrimary} onClick={() => void verify()} disabled={busy}>{busy ? 'Verifying…' : 'Verify'}</button></div>
        {result && <div role="status" className="mt-4 space-y-1"><Pill tone={tone[result.state]}>{result.state}</Pill> {result.simulated && <Pill tone="cyan">simulated</Pill>}<p className="text-sm text-slate-300">{result.message}</p></div>}
      </Card>
    </div>
  )
}
