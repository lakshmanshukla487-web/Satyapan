import { useState } from 'react'
import { Cpu, HardDrive, PlugZap } from 'lucide-react'
import { devlab } from '../../features/devlab/devlabService'
import type { DevDetector, DevModelsStatus } from '../../types/devlab'
import { Card, ErrorBox, Pill, SectionTitle, Spinner, btnGhost } from '../ui'

const TONE = { available: 'green', unavailable: 'red', not_loaded: 'amber', disabled: 'slate' } as const
const TEXT = { available: 'Inference available', unavailable: 'Unavailable', not_loaded: 'Not loaded yet', disabled: 'Switched off' } as const
const mb = (n?: number) => (n ? `${(n / 1024 / 1024).toFixed(n > 1024 * 1024 * 100 ? 0 : 1)} MB` : '')
const ERROR_TEXT: Record<string, string> = {
  MODEL_NOT_DOWNLOADED: 'The weights are not on this server.', WEIGHTS_INCOMPLETE: 'The weights do not fit the model configuration (missing or wrongly shaped layers); refusing to run with random layers.',
  DEPENDENCY_MISSING: 'A Python package the model needs is not installed (pip install -r requirements-ml.txt).', LOAD_FAILED: 'Loading failed; see the server log.',
  NOT_INTEGRATED: 'This detector is a placeholder: its weights and preprocessing were never verified, so it never produces a score.', CHECKPOINT_MISMATCH: 'The checkpoint does not match the network.',
  LABEL_MAPPING_UNKNOWN: "The model's label map does not say which class is 'fake'.",
}

function DetectorCard({ d, onChecked }: { d: DevDetector; onChecked: (s: DevModelsStatus) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const check = async () => { setBusy(true); setErr(null); try { onChecked(await devlab.checkModel(d.name)) } catch (e) { setErr(e instanceof Error ? e.message : 'Check failed.') } finally { setBusy(false) } }
  return (
    <Card className="!p-4" >
      <div className="flex items-start justify-between gap-2">
        <div><h3 className="font-medium text-white">{d.label}</h3><p className="font-mono text-xs text-slate-500">{d.name}{d.media_types.length ? ` · ${d.media_types.join(', ')}` : ''}</p></div>
        <Pill tone={TONE[d.inference]}>{TEXT[d.inference]}</Pill>
      </div>
      <dl className="mt-3 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-slate-500">Model</dt><dd className="break-all text-slate-300">{d.model_id ?? '—'}</dd>
        <dt className="text-slate-500">Version</dt><dd className="font-mono text-slate-300">{d.model_version || '—'}</dd>
        <dt className="text-slate-500">Weights</dt><dd className="text-slate-300">{d.weights.present ? `${d.weights.file} ${mb(d.weights.size_bytes)} in ${d.weights.location}` : d.weights.location ? `missing (${d.weights.location})` : 'none'}</dd>
        <dt className="text-slate-500">Threshold</dt><dd className="text-slate-300">{d.threshold ?? '—'}{d.score_kind ? ` · ${d.score_kind}` : ''}</dd>
      </dl>
      {d.error_code && <p className="mt-2 text-xs text-red-300">{d.error_code}: {ERROR_TEXT[d.error_code] ?? 'See the server log.'}</p>}
      {d.load_problem && <p className="mt-1 break-all text-xs text-slate-500">Load problem: {JSON.stringify(d.load_problem)}</p>}
      {!d.weights.present && d.weights.hint && <p className="mt-1 text-xs text-amber-300">{d.weights.hint}</p>}
      <p className="mt-2 text-xs text-slate-400">{d.score_meaning}</p>
      {d.video_method && <p className="mt-1 text-xs text-slate-500">{d.video_method}</p>}
      {d.inference === 'not_loaded' && <button className={`${btnGhost} mt-3`} disabled={busy} onClick={() => void check()}>{busy ? <Spinner /> : <PlugZap className="h-4 w-4" />}Load and check now</button>}
      {err && <div className="mt-2"><ErrorBox message={err} /></div>}
    </Card>
  )
}

/** Which detectors can really run on this server, and why not when they cannot. Never inferred from a config file alone. */
export function ModelHealth({ status, onChange }: { status: DevModelsStatus; onChange: (s: DevModelsStatus) => void }) {
  const deps = Object.entries(status.dependencies)
  return (
    <section className="space-y-3">
      <SectionTitle hint="The same detector objects the live pipeline uses. A model that cannot load is reported as unavailable on every test; no score is ever simulated."
        right={<Pill tone="slate"><Cpu className="h-3 w-3" />CPU</Pill>}>Models on this server</SectionTitle>
      <div className="grid gap-3 lg:grid-cols-3">{status.detectors.map((d) => <DetectorCard key={d.name} d={d} onChecked={onChange} />)}</div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <HardDrive className="h-3.5 w-3.5" />Dependencies:
        {deps.map(([k, ok]) => <Pill key={k} tone={ok ? 'green' : 'amber'}>{k} {ok ? 'installed' : 'missing'}</Pill>)}
      </div>
      <p className="text-xs text-slate-500">
        Limits: {status.limits.max_upload_mb} MB per file, {status.limits.max_items_per_job} files and {status.limits.max_job_mb} MB per job, video up to {status.limits.max_video_seconds} s
        ({status.limits.video_frames_default} frames sampled by default, at most {status.limits.max_video_frames}), audio up to {status.limits.max_audio_seconds} s. Results are deleted after {status.limits.retention_hours} h.
        {!status.preload_models && ' PRELOAD_MODELS is off: models load on first use.'} New weights are picked up after a server restart.
      </p>
    </section>
  )
}
