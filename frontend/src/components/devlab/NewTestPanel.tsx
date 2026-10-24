import { useEffect, useRef, useState } from 'react'
import { Database, FolderOpen, Play, Trash2, UploadCloud, X } from 'lucide-react'
import { devlab } from '../../features/devlab/devlabService'
import { ApiError } from '../../services/apiClient'
import type { DevAggregation, DevDatasets, DevJobOptions, DevLabel, DevMedia, DevModelsStatus } from '../../types/devlab'
import { Card, ErrorBox, Pill, SectionTitle, Spinner, btnGhost, btnPrimary, inputCls } from '../ui'

const EXT: Record<string, DevMedia> = { jpg: 'image', jpeg: 'image', png: 'image', wav: 'audio', flac: 'audio', ogg: 'audio', mp3: 'audio', m4a: 'audio', mp4: 'video', m4v: 'video', mov: 'video', webm: 'video', mkv: 'video', avi: 'video' }
const ACCEPT = Object.keys(EXT).map((e) => `.${e}`).join(',')
const REAL = new Set(['real', 'bonafide', 'bona_fide', 'bona-fide', 'genuine', 'authentic', 'live', 'original'])
const FAKE = new Set(['fake', 'spoof', 'deepfake', 'deepfakes', 'synthetic', 'generated', 'manipulated', 'attack'])
const CONCURRENCY = 2
type LabelMode = 'none' | 'real' | 'fake' | 'folders'
type UpState = 'ready' | 'uploading' | 'accepted' | 'rejected' | 'skipped'
interface Picked { key: string; file: File; path: string; media: DevMedia | null; label: DevLabel; state: UpState; message?: string }
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const mediaOf = (name: string) => EXT[name.split('.').pop()?.toLowerCase() ?? ''] ?? null
const fmt = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)
function folderLabel(path: string): DevLabel {
  const parts = path.split('/').slice(0, -1).map((p) => p.toLowerCase()).reverse()
  for (const p of parts) { if (REAL.has(p)) return 'real'; if (FAKE.has(p)) return 'fake' }
  return ''
}

function Options({ opts, setOpts, max }: { opts: DevJobOptions; setOpts: (o: DevJobOptions) => void; max: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="block text-sm text-slate-300">Video frames per clip
        <input type="number" min={1} max={max} className={inputCls} value={opts.video_frames} onChange={(e) => setOpts({ ...opts, video_frames: Math.max(1, Math.min(max, Number(e.target.value) || 1)) })} /></label>
      <label className="block text-sm text-slate-300">Video score
        <select className={inputCls} value={opts.aggregation} onChange={(e) => setOpts({ ...opts, aggregation: e.target.value as DevAggregation })}>
          <option value="median">Median of frames (live-policy majority rule)</option><option value="mean">Mean of frames</option><option value="top_quarter">Worst quarter of frames</option>
        </select></label>
      <label className="mt-6 flex items-start gap-2 text-sm text-slate-300"><input type="checkbox" className="mt-1" checked={opts.score_low_quality} onChange={(e) => setOpts({ ...opts, score_low_quality: e.target.checked })} />
        <span>Also score poor-quality input<span className="block text-xs text-slate-500">Off = same rule as live sessions (too dark, tiny, silent or very short samples are not scored).</span></span></label>
    </div>
  )
}

/** Start a test: upload files (single file or a whole folder, optionally labelled) or pick an authorised local dataset. */
export function NewTestPanel({ models, onStarted }: { models: DevModelsStatus; onStarted: (jobId: string) => void }) {
  const [tab, setTab] = useState<'upload' | 'dataset'>('upload')
  const [picks, setPicks] = useState<Picked[]>([])
  const [mode, setMode] = useState<LabelMode>('none')
  const [name, setName] = useState('')
  const [opts, setOpts] = useState<DevJobOptions>({ aggregation: 'median', video_frames: models.limits.video_frames_default, score_low_quality: false })
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ds, setDs] = useState<DevDatasets | null>(null)
  const [dsName, setDsName] = useState('')
  const [dsTypes, setDsTypes] = useState<DevMedia[]>(['image', 'video', 'audio'])
  const [dsLimit, setDsLimit] = useState(models.limits.max_items_per_job)
  const filesRef = useRef<HTMLInputElement | null>(null)
  const folderRef = useRef<HTMLInputElement | null>(null)
  const abort = useRef<AbortController | null>(null)
  const maxBytes = models.limits.max_upload_mb * 1024 * 1024

  useEffect(() => { folderRef.current?.setAttribute('webkitdirectory', ''); folderRef.current?.setAttribute('directory', '') }, [])
  useEffect(() => { if (tab === 'dataset' && ds === null) devlab.datasets().then((d) => { setDs(d); if (d.datasets[0]) setDsName(d.datasets[0].name) }).catch((e) => setErr(e instanceof Error ? e.message : 'Could not list datasets.')) }, [tab, ds])
  useEffect(() => () => abort.current?.abort(), [])

  const labelFor = (p: { path: string }, m: LabelMode): DevLabel => (m === 'real' ? 'real' : m === 'fake' ? 'fake' : m === 'folders' ? folderLabel(p.path) : '')
  const add = (list: FileList | null) => {
    if (!list) return
    const room = models.limits.max_items_per_job - picks.length
    const next: Picked[] = Array.from(list).slice(0, Math.max(0, room)).map((file, i) => {
      const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      const media = mediaOf(file.name)
      const tooBig = file.size > maxBytes
      return { key: `${Date.now()}-${i}-${path}`, file, path, media, label: labelFor({ path }, mode), state: media && !tooBig ? 'ready' : 'skipped',
        message: !media ? 'Unsupported file type' : tooBig ? `Larger than ${models.limits.max_upload_mb} MB` : undefined }
    })
    setPicks((p) => [...p, ...next])
    if (list.length > room) setErr(`Only ${models.limits.max_items_per_job} files fit in one job; the rest were not added.`)
  }
  const applyMode = (m: LabelMode) => { setMode(m); setPicks((p) => p.map((x) => ({ ...x, label: labelFor(x, m) }))) }
  const ready = picks.filter((p) => p.state === 'ready')
  const labelled = ready.filter((p) => p.label).length

  const runUpload = async () => {
    if (!ready.length) return
    setBusy(true); setErr(null)
    const ac = new AbortController(); abort.current = ac
    let jobId: string | null = null
    try {
      const job = await devlab.createUploadJob(name.trim() || `Upload ${new Date().toLocaleString()}`, opts)
      jobId = job.id
      setProgress({ done: 0, total: ready.length })
      const queue = [...ready]
      let done = 0, accepted = 0
      const worker = async () => {
        for (let p = queue.shift(); p && !ac.signal.aborted; p = queue.shift()) {
          const cur = p
          setPicks((all) => all.map((x) => (x.key === cur.key ? { ...x, state: 'uploading' } : x)))
          let state: UpState = 'rejected', message: string | undefined
          for (let attempt = 0; attempt < 4; attempt++) {  // only a rate-limit refusal is retried (the server did not accept the file)
            try { await devlab.uploadItem(jobId as string, cur.file, cur.label, ac.signal); state = 'accepted'; accepted++; break }
            catch (e) {
              if (e instanceof ApiError && e.status === 429 && e.code === 'RATE_LIMITED' && attempt < 3) { await sleep(Math.min(15, e.retryAfter ?? 3) * 1000); continue }
              message = e instanceof Error ? e.message : 'Upload failed.'
              break
            }
          }
          done++
          setProgress({ done, total: ready.length })
          setPicks((all) => all.map((x) => (x.key === cur.key ? { ...x, state, message } : x)))
        }
      }
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, ready.length) }, worker))
      if (ac.signal.aborted) { await devlab.remove(jobId).catch(() => undefined); setErr('Upload cancelled. Nothing was tested.'); return }
      if (!accepted) { await devlab.remove(jobId).catch(() => undefined); setErr('None of the files was accepted (see the reasons in the list).'); return }
      await devlab.start(jobId)
      onStarted(jobId)
      setPicks((all) => all.filter((x) => x.state !== 'accepted'))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not start the test.')
      if (jobId) await devlab.remove(jobId).catch(() => undefined)
    } finally { setBusy(false); setProgress(null); abort.current = null }
  }

  const runDataset = async () => {
    if (!dsName) return
    setBusy(true); setErr(null)
    try { const job = await devlab.createDatasetJob(dsName, dsTypes, dsLimit, name.trim(), opts); onStarted(job.id) }
    catch (e) { setErr(e instanceof Error ? e.message : 'Could not start the test.') } finally { setBusy(false) }
  }
  const selected = ds?.datasets.find((d) => d.name === dsName)

  return (
    <Card className="space-y-4">
      <SectionTitle hint="Runs offline: no customer session, no camera, no officer. Results stay in this lab and are never shown to officers or customers.">New test</SectionTitle>
      <div role="tablist" className="flex gap-2">
        <button role="tab" aria-selected={tab === 'upload'} onClick={() => setTab('upload')} className={`rounded-full border px-3 py-1 text-sm ${tab === 'upload' ? 'border-brand-400/60 bg-brand-400/15 text-brand-300' : 'border-white/10 text-slate-400 hover:text-white'}`}><UploadCloud className="mr-1 inline h-4 w-4" />Upload files</button>
        <button role="tab" aria-selected={tab === 'dataset'} onClick={() => setTab('dataset')} className={`rounded-full border px-3 py-1 text-sm ${tab === 'dataset' ? 'border-brand-400/60 bg-brand-400/15 text-brand-300' : 'border-white/10 text-slate-400 hover:text-white'}`}><Database className="mr-1 inline h-4 w-4" />Local dataset</button>
      </div>
      <label className="block text-sm text-slate-300">Name (optional)<input className={inputCls} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: FaceForensics sample, Oct build" /></label>
      <Options opts={opts} setOpts={setOpts} max={models.limits.max_video_frames} />

      {tab === 'upload' ? (<>
        <div className="flex flex-wrap items-center gap-2">
          <input ref={filesRef} type="file" multiple accept={ACCEPT} className="sr-only" onChange={(e) => { add(e.target.files); e.target.value = '' }} />
          <input ref={folderRef} type="file" multiple className="sr-only" onChange={(e) => { add(e.target.files); e.target.value = '' }} />
          <button className={btnGhost} disabled={busy} onClick={() => filesRef.current?.click()}><UploadCloud className="h-4 w-4" />Choose files</button>
          <button className={btnGhost} disabled={busy} onClick={() => folderRef.current?.click()}><FolderOpen className="h-4 w-4" />Choose a folder</button>
          {picks.length > 0 && <button className={btnGhost} disabled={busy} onClick={() => setPicks([])}><Trash2 className="h-4 w-4" />Clear list</button>}
          <label className="ml-auto text-sm text-slate-300">Ground truth{' '}
            <select className={`${inputCls} !mt-0 !inline-block !w-auto`} value={mode} disabled={busy} onChange={(e) => applyMode(e.target.value as LabelMode)}>
              <option value="none">None (no accuracy metrics)</option><option value="real">All files are real</option><option value="fake">All files are fake</option><option value="folders">From folder names (real/ fake/ …)</option>
            </select></label>
        </div>
        <p className="text-xs text-slate-500">Images: JPEG, PNG. Audio: WAV, FLAC, OGG (MP3, M4A if ffmpeg is installed). Video: MP4, MOV, WebM, MKV, AVI. The server identifies files by their content and rejects anything else. Labels can be changed per file below.</p>
        {picks.length > 0 && (
          <div className="max-h-72 overflow-y-auto rounded-xl border border-white/[0.07]">
            <table className="w-full text-left text-sm"><thead className="sticky top-0 bg-ink-900 text-xs text-slate-500"><tr><th className="p-2">File</th><th className="p-2">Type</th><th className="p-2">Size</th><th className="p-2">Label</th><th className="p-2">Status</th><th className="p-2"><span className="sr-only">Remove</span></th></tr></thead>
              <tbody>{picks.map((p) => (
                <tr key={p.key} className="border-t border-white/[0.06]">
                  <td className="max-w-[16rem] truncate p-2 text-slate-300" title={p.path}>{p.path}</td>
                  <td className="p-2 text-slate-400">{p.media ?? '—'}</td>
                  <td className="whitespace-nowrap p-2 text-slate-400">{fmt(p.file.size)}</td>
                  <td className="p-2"><select aria-label={`Label for ${p.path}`} className="rounded border border-white/10 bg-ink-950 px-1 py-0.5 text-xs text-slate-200" value={p.label} disabled={busy || p.state === 'skipped'}
                    onChange={(e) => { const v = e.target.value as DevLabel; setPicks((all) => all.map((x) => (x.key === p.key ? { ...x, label: v } : x))) }}><option value="">unlabelled</option><option value="real">real</option><option value="fake">fake</option></select></td>
                  <td className="p-2 text-xs">{p.state === 'uploading' ? <span className="inline-flex items-center gap-1 text-cyan-300"><Spinner className="h-3 w-3" />uploading</span>
                    : p.state === 'accepted' ? <span className="text-emerald-300">accepted</span> : p.state === 'rejected' ? <span className="text-red-300" title={p.message}>rejected: {p.message}</span>
                    : p.state === 'skipped' ? <span className="text-amber-300">{p.message}</span> : <span className="text-slate-500">ready</span>}</td>
                  <td className="p-2"><button aria-label={`Remove ${p.path}`} disabled={busy} className="text-slate-500 hover:text-red-300" onClick={() => setPicks((all) => all.filter((x) => x.key !== p.key))}><X className="h-4 w-4" /></button></td>
                </tr>))}</tbody></table>
          </div>)}
        <div className="flex flex-wrap items-center gap-3">
          <button className={btnPrimary} disabled={busy || !ready.length} onClick={() => void runUpload()}>{busy ? <Spinner /> : <Play className="h-4 w-4" />}{ready.length === 1 ? 'Test this file' : `Test ${ready.length} files`}</button>
          {busy && progress && <><span className="text-sm text-slate-400">Uploading {progress.done}/{progress.total}…</span><button className={btnGhost} onClick={() => abort.current?.abort()}>Cancel upload</button></>}
          {!busy && ready.length > 0 && <Pill tone={labelled ? 'green' : 'slate'}>{labelled ? `${labelled} of ${ready.length} labelled` : 'unlabelled: results only, no accuracy'}</Pill>}
        </div>
      </>) : (
        <div className="space-y-3">
          {ds === null ? <p className="text-sm text-slate-400">Loading datasets…</p> : !ds.available ? (
            <p className="text-sm text-slate-400">{ds.configured ? 'The configured dataset folder (DEVLAB_DATASET_DIR) does not exist on the server.' : 'No local dataset folder is configured. Set DEVLAB_DATASET_DIR to a folder with one sub-folder per dataset (files under real/ and fake/, or a labels.csv).'}</p>
          ) : ds.datasets.length === 0 ? <p className="text-sm text-slate-400">The dataset folder is empty.</p> : (<>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block text-sm text-slate-300">Dataset<select className={inputCls} value={dsName} onChange={(e) => setDsName(e.target.value)}>{ds.datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}</select></label>
              <fieldset className="text-sm text-slate-300"><legend>Media types</legend><div className="mt-2 flex gap-3">{(['image', 'video', 'audio'] as DevMedia[]).map((t) => (
                <label key={t} className="flex items-center gap-1"><input type="checkbox" checked={dsTypes.includes(t)} onChange={(e) => setDsTypes((x) => (e.target.checked ? [...x, t] : x.filter((y) => y !== t)))} />{t}</label>))}</div></fieldset>
              <label className="block text-sm text-slate-300">At most (files)<input type="number" min={1} max={models.limits.max_items_per_job} className={inputCls} value={dsLimit} onChange={(e) => setDsLimit(Math.max(1, Math.min(models.limits.max_items_per_job, Number(e.target.value) || 1)))} /></label>
            </div>
            {selected && <p className="text-xs text-slate-400">{selected.files} files ({Object.entries(selected.by_media).map(([k, v]) => `${v} ${k}`).join(', ')}); {selected.labelled} labelled: {selected.real} real, {selected.fake} fake.</p>}
            <button className={btnPrimary} disabled={busy || !dsName || !dsTypes.length} onClick={() => void runDataset()}>{busy ? <Spinner /> : <Play className="h-4 w-4" />}Run on dataset</button>
          </>)}
        </div>)}
      {err && <ErrorBox message={err} />}
    </Card>
  )
}
