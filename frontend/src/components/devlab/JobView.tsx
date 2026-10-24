import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Ban, Download, Search, Trash2 } from 'lucide-react'
import { devlab } from '../../features/devlab/devlabService'
import { useAsync } from '../../hooks/useAsync'
import type { DevItem, DevItemStatus, DevJobDetail, DevMetrics } from '../../types/devlab'
import { Card, ErrorBox, Loading, Modal, Pill, SectionTitle, Spinner, btnDanger, btnGhost, inputCls } from '../ui'
import { fmtTime } from '../../utils/format'

const POLL_MS = 2000
const PAGE = 50
const ITEM_TONE: Record<DevItemStatus, 'green' | 'red' | 'amber' | 'slate' | 'cyan'> = { done: 'green', error: 'red', unavailable: 'red', low_quality: 'amber', cancelled: 'slate', queued: 'slate', running: 'cyan' }
const JOB_TONE = { draft: 'slate', queued: 'amber', running: 'cyan', completed: 'green', cancelled: 'slate', failed: 'red' } as const
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`)
const num = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? '—' : v.toFixed(d))
type Sort = 'index' | 'filename' | 'score' | 'duration'

function MetricsBlock({ m }: { m: DevMetrics }) {
  return (
    <Card className="!p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium text-white">{m.media_type} · <span className="font-mono text-sm">{m.detector}</span></h3>
        <span className="text-xs text-slate-400">{m.evaluated} evaluated of {m.samples} · {m.labelled} labelled ({m.class_support.real} real, {m.class_support.fake} fake){m.thresholds.length ? ` · threshold ${m.thresholds.join(', ')}` : ''}</span></div>
      {m.available ? (
        <div className="mt-3 grid gap-4 md:grid-cols-[1fr,auto]">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
            {([['Accuracy', pct(m.accuracy)], ['Balanced accuracy', pct(m.balanced_accuracy)], ['Precision (fake)', pct(m.precision)], ['Recall (fake)', pct(m.recall)],
              ['Specificity (real)', pct(m.specificity)], ['F1', num(m.f1)], ['ROC AUC', num(m.roc_auc)], ['FP / FN', `${m.false_positive ?? 0} / ${m.false_negative ?? 0}`]] as const).map(([k, v]) => (
              <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-semibold tabular-nums text-white">{v}</dd></div>))}
          </dl>
          {m.confusion_matrix && (
            <table className="text-center text-xs" aria-label="Confusion matrix (rows: ground truth, columns: prediction)">
              <thead><tr><th className="p-1 text-slate-500">truth ↓ / predicted →</th><th className="p-1 text-slate-400">real</th><th className="p-1 text-slate-400">fake</th></tr></thead>
              <tbody>{m.confusion_matrix.matrix.map((row, i) => (
                <tr key={i}><th className="p-1 text-slate-400">{m.confusion_matrix?.labels[i]}</th>{row.map((v, j) => <td key={j} className={`min-w-12 rounded p-2 font-semibold tabular-nums ${i === j ? 'bg-emerald-400/15 text-emerald-200' : 'bg-red-400/10 text-red-200'}`}>{v}</td>)}</tr>))}</tbody>
            </table>)}
        </div>) : null}
      {m.excluded.length > 0 && <p className="mt-2 text-xs text-slate-400">Excluded: {m.excluded.map((e) => `${e.count} ${e.text}`).join('; ')}.</p>}
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-500">{m.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </Card>
  )
}

function ItemDetail({ jobId, item, onClose }: { jobId: string; item: DevItem | null; onClose: () => void }) {
  const q = useAsync(() => (item ? devlab.item(jobId, item.id) : Promise.resolve(null)), [jobId, item?.id])
  const it = q.data ?? item
  const frames = (it?.details?.frames as { index: number; time_s: number; status: string; score?: number | null; crop?: string }[] | undefined) ?? []
  return (
    <Modal open={item !== null} title={it ? it.filename : 'Result'} onClose={onClose}>
      {it && (
        <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1 text-sm">
          <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
            {([['Test ID', it.id], ['Media', `${it.media_type} (${it.file_format}), ${(it.size_bytes / 1024).toFixed(0)} KB`], ['Ground truth', it.label || 'unlabelled'], ['Status', it.status],
              ['Detector', `${it.detector || '—'} ${it.model_id ? `(${it.model_id})` : ''}`], ['Model version', it.model_version || '—'], ['Score', it.score === null ? 'not produced' : it.score.toFixed(4)],
              ['Score meaning', it.score_kind || '—'], ['Threshold', it.threshold ?? '—'], ['Prediction', it.prediction || '—'], ["Model's own label", it.model_label || '—'],
              ['Processing time', it.duration_ms === null ? '—' : `${(it.duration_ms / 1000).toFixed(2)} s`], ['Frames analysed', it.frames_analyzed ?? '—'], ['Segments analysed', it.segments_analyzed ?? '—'],
              ['Warnings', it.warnings.length ? it.warnings.join(', ') : 'none'], ['Error', it.error_code || 'none']] as const).map(([k, v]) => (
              <Fragment key={k}><dt className="text-slate-500">{k}</dt><dd className="break-all text-slate-200">{String(v)}</dd></Fragment>))}
          </dl>
          {frames.length > 0 && (
            <div><p className="mb-1 text-xs uppercase tracking-wider text-slate-500">Sampled frames</p>
              <ul className="grid grid-cols-2 gap-1 text-xs sm:grid-cols-3">{frames.map((f) => <li key={f.index} className="rounded border border-white/[0.06] px-2 py-1 text-slate-300">t={f.time_s}s · {f.score === undefined || f.score === null ? f.status : f.score.toFixed(3)}{f.crop === 'none' ? ' · no face crop' : ''}</li>)}</ul></div>)}
          {q.loading && <p className="text-xs text-slate-500">Loading details…</p>}
          {it.details && <details><summary className="cursor-pointer text-xs text-slate-400">Raw detector details</summary><pre className="mt-2 max-h-64 overflow-auto rounded bg-ink-950 p-2 text-[11px] text-slate-300">{JSON.stringify({ ...it.details, frames: undefined }, null, 2)}</pre></details>}
        </div>)}
    </Modal>
  )
}

/** One job: live progress, cancel / delete / export, dataset summary, evaluation metrics (when labelled) and every result. */
export function JobView({ jobId, onDeleted, onChanged }: { jobId: string; onDeleted: () => void; onChanged: () => void }) {
  const q = useAsync<DevJobDetail>(() => devlab.detail(jobId), [jobId])
  const d = q.data
  const running = d ? d.job.status === 'queued' || d.job.status === 'running' : false
  const { reload } = q
  useEffect(() => { if (!running) return; const t = window.setInterval(reload, POLL_MS); return () => window.clearInterval(t) }, [running, reload])
  const wasRunning = useRef(false)
  useEffect(() => { wasRunning.current = false }, [jobId])
  useEffect(() => { if (wasRunning.current && !running) onChanged(); wasRunning.current = running }, [running, onChanged])  // finished: refresh the job list
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [fMedia, setFMedia] = useState('')
  const [fPred, setFPred] = useState('')
  const [fCorrect, setFCorrect] = useState('')
  const [sort, setSort] = useState<Sort>('index')
  const [desc, setDesc] = useState(false)
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<DevItem | null>(null)
  const act = async (what: 'cancel' | 'delete' | 'csv' | 'json') => {
    setBusy(what); setErr(null)
    try {
      if (what === 'cancel') { await devlab.cancel(jobId); reload(); onChanged() }
      else if (what === 'delete') { await devlab.remove(jobId); onDeleted() }
      else await devlab.exportResults(jobId, what)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Action failed.') } finally { setBusy(null) }
  }
  const rows = useMemo(() => {
    const items = d?.items ?? []
    const f = items.filter((it) => (!query || it.filename.toLowerCase().includes(query.toLowerCase())) && (!fStatus || it.status === fStatus) && (!fMedia || it.media_type === fMedia)
      && (!fPred || it.prediction === fPred) && (!fCorrect || (fCorrect === 'right' ? it.correct === true : fCorrect === 'wrong' ? it.correct === false : it.correct === null)))
    const key = (it: DevItem) => (sort === 'filename' ? it.filename.toLowerCase() : sort === 'score' ? (it.score ?? -1) : sort === 'duration' ? (it.duration_ms ?? -1) : it.index)
    return [...f].sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1) })
  }, [d, query, fStatus, fMedia, fPred, fCorrect, sort, desc])
  useEffect(() => setPage(0), [query, fStatus, fMedia, fPred, fCorrect, sort, desc, jobId])
  if (q.loading && !d) return <Loading />
  if (!d) return <ErrorBox message={q.error ?? 'Job not found.'} onRetry={reload} />
  const j = d.job
  const progress = j.total_items ? Math.round((j.finished_items / j.total_items) * 100) : 0
  const sortBtn = (s: Sort, label: string) => <button className="underline-offset-2 hover:underline" onClick={() => { if (sort === s) setDesc(!desc); else { setSort(s); setDesc(s !== 'index' && s !== 'filename') } }}>{label}{sort === s ? (desc ? ' ↓' : ' ↑') : ''}</button>
  const shown = rows.slice(page * PAGE, (page + 1) * PAGE)
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-lg font-medium text-white">{j.name}</h2><p className="text-xs text-slate-500">{j.source === 'dataset' ? `Dataset ${j.dataset}` : 'Uploaded files'} · created {fmtTime(j.created_at)} · results kept until {fmtTime(j.expires_at)} · <span className="font-mono">{j.id.slice(0, 8)}</span></p>
            <p className="text-xs text-slate-500">Options: video {j.options.video_frames} frames, {j.options.aggregation.replace('_', ' ')} score{j.options.score_low_quality ? ', poor-quality input scored' : ''}</p></div>
          <div className="flex flex-wrap gap-2">
            <Pill tone={JOB_TONE[j.status]}>{running && <Spinner className="h-3 w-3" />}{j.status}{j.cancel_requested && running ? ' (stopping)' : ''}</Pill>
            {running && <button className={btnDanger} disabled={busy !== null || j.cancel_requested} onClick={() => void act('cancel')}><Ban className="h-4 w-4" />Cancel</button>}
            <button className={btnGhost} disabled={busy !== null} onClick={() => void act('csv')}><Download className="h-4 w-4" />CSV</button>
            <button className={btnGhost} disabled={busy !== null} onClick={() => void act('json')}>JSON</button>
            {!running && <button className={btnGhost} disabled={busy !== null} onClick={() => void act('delete')}><Trash2 className="h-4 w-4" />Delete</button>}
          </div>
        </div>
        <div role="progressbar" aria-label="Tests finished" aria-valuemin={0} aria-valuemax={j.total_items} aria-valuenow={j.finished_items} className="h-2 overflow-hidden rounded-full bg-ink-700"><div className="h-2 rounded-full bg-gradient-to-r from-brand-400 to-emerald-400 transition-all" style={{ width: `${progress}%` }} /></div>
        <div className="flex flex-wrap gap-2 text-xs">{Object.entries(j.counts).map(([k, v]) => <Pill key={k} tone={ITEM_TONE[k as DevItemStatus] ?? 'slate'}>{v} {k.replace('_', ' ')}</Pill>)}<span className="text-slate-500">{j.finished_items}/{j.total_items} finished</span></div>
        {j.error && <ErrorBox message={j.error} />}
        {err && <ErrorBox message={err} />}
        {q.error && <p className="text-xs text-amber-300">Could not refresh just now ({q.error}).</p>}
      </Card>

      <section className="space-y-3">
        <SectionTitle hint="Counts that need no labels: how many were scored and what the detector predicted.">Summary</SectionTitle>
        <div className="grid gap-3 md:grid-cols-3">{Object.entries(d.summary.by_media).map(([m, s]) => (
          <Card key={m} className="!p-4"><p className="text-xs uppercase tracking-wider text-slate-500">{m}</p><p className="mt-1 text-2xl font-semibold text-white">{s.scored}<span className="text-sm font-normal text-slate-500"> of {s.count} scored</span></p>
            <p className="text-xs text-slate-400">{s.predicted_fake} predicted fake · {s.predicted_real} predicted real · mean score {num(s.mean_score)} · {s.mean_duration_ms === null ? '—' : `${(s.mean_duration_ms / 1000).toFixed(2)} s`} per file</p></Card>))}</div>
      </section>

      <section className="space-y-3">
        <SectionTitle hint="Positive class = fake. Only samples with a ground-truth label and a real detector result count; everything else is listed as excluded.">Evaluation</SectionTitle>
        {d.metrics.map((m) => <MetricsBlock key={`${m.media_type}-${m.detector}`} m={m} />)}
      </section>

      <Card>
        <SectionTitle right={<span className="text-xs text-slate-500">{rows.length} of {d.items.length}</span>}>Results</SectionTitle>
        <div className="mb-3 flex flex-wrap gap-2">
          <label className="relative min-w-48 flex-1"><span className="sr-only">Search by file name</span><Search className="absolute left-3 top-3 h-4 w-4 text-slate-500" /><input className={`${inputCls} !mt-0 pl-9`} placeholder="Search by file name" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          {([[fStatus, setFStatus, 'Status', ['done', 'low_quality', 'unavailable', 'error', 'cancelled', 'queued', 'running']], [fMedia, setFMedia, 'Media', ['image', 'video', 'audio']],
            [fPred, setFPred, 'Prediction', ['fake', 'real']], [fCorrect, setFCorrect, 'Correctness', ['right', 'wrong', 'unknown']]] as const).map(([v, set, label, opts]) => (
            <select key={label} aria-label={label} className={`${inputCls} !mt-0 !w-auto`} value={v} onChange={(e) => set(e.target.value)}><option value="">{label}: all</option>{opts.map((o) => <option key={o} value={o}>{o.replace('_', ' ')}</option>)}</select>))}
        </div>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-slate-500"><tr><th className="p-2">{sortBtn('index', '#')}</th><th className="p-2">{sortBtn('filename', 'File')}</th><th className="p-2">Media</th><th className="p-2">Truth</th><th className="p-2">Status</th><th className="p-2">{sortBtn('score', 'Score')}</th><th className="p-2">Prediction</th><th className="p-2">{sortBtn('duration', 'Time')}</th><th className="p-2">Notes</th></tr></thead>
          <tbody>{shown.map((it) => (
            <tr key={it.id} className="cursor-pointer border-t border-white/[0.06] hover:bg-white/[0.03]" onClick={() => setOpen(it)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setOpen(it) }}>
              <td className="p-2 text-slate-500">{it.index + 1}</td>
              <td className="max-w-[18rem] truncate p-2 text-slate-200" title={it.filename}>{it.filename}</td>
              <td className="p-2 text-slate-400">{it.media_type}</td>
              <td className="p-2 text-slate-400">{it.label || '—'}</td>
              <td className="p-2"><Pill tone={ITEM_TONE[it.status]}>{it.status.replace('_', ' ')}</Pill></td>
              <td className="p-2 tabular-nums text-slate-200">{it.score === null ? '—' : it.score.toFixed(3)}</td>
              <td className="p-2">{it.prediction ? <span className={it.correct === false ? 'text-red-300' : it.correct ? 'text-emerald-300' : 'text-slate-200'}>{it.prediction}{it.correct === false ? ' ✗' : it.correct ? ' ✓' : ''}</span> : '—'}</td>
              <td className="whitespace-nowrap p-2 text-slate-400">{it.duration_ms === null ? '—' : `${(it.duration_ms / 1000).toFixed(2)} s`}</td>
              <td className="max-w-[14rem] truncate p-2 text-xs text-slate-500" title={[it.error_code, ...it.warnings].filter(Boolean).join(', ')}>{[it.error_code, ...it.warnings].filter(Boolean).join(', ') || (it.frames_analyzed ? `${it.frames_analyzed} frames` : it.segments_analyzed ? `${it.segments_analyzed} windows` : '')}</td>
            </tr>))}</tbody></table></div>
        {rows.length > PAGE && <div className="mt-3 flex items-center justify-end gap-2 text-xs text-slate-400"><button className={btnGhost} disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>Page {page + 1} of {Math.ceil(rows.length / PAGE)}<button className={btnGhost} disabled={(page + 1) * PAGE >= rows.length} onClick={() => setPage(page + 1)}>Next</button></div>}
      </Card>
      <ItemDetail jobId={jobId} item={open} onClose={() => setOpen(null)} />
    </div>
  )
}
