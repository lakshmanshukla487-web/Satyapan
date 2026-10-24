import { useCallback, useEffect, useState } from 'react'
import { FlaskConical, RefreshCw, ShieldCheck } from 'lucide-react'
import { devlab } from '../features/devlab/devlabService'
import { useAsync } from '../hooks/useAsync'
import { ModelHealth } from '../components/devlab/ModelHealth'
import { NewTestPanel } from '../components/devlab/NewTestPanel'
import { JobView } from '../components/devlab/JobView'
import { Card, Empty, ErrorBox, Loading, Pill, SectionTitle, Spinner, btnGhost } from '../components/ui'
import { fmtTime } from '../utils/format'
import type { DevModelsStatus } from '../types/devlab'

const JOB_TONE = { draft: 'slate', queued: 'amber', running: 'cyan', completed: 'green', cancelled: 'slate', failed: 'red' } as const

/** Developer-only model test lab (/developer): evaluates the real deepfake detectors on offline test files and datasets, completely
 *  separate from customer sessions, officer dashboards, evidence and WebSockets. The backend enforces the developer role on every call. */
export default function DeveloperLabPage() {
  const models = useAsync(() => devlab.models(), [])
  const jobs = useAsync(() => devlab.jobs(), [])
  const [status, setStatus] = useState<DevModelsStatus | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  useEffect(() => { if (models.data) setStatus(models.data) }, [models.data])
  useEffect(() => { if (!selected && jobs.data?.items[0]) setSelected(jobs.data.items[0].id) }, [jobs.data, selected])
  const anyActive = Boolean(jobs.data?.items.some((j) => j.status === 'queued' || j.status === 'running'))
  const { reload: reloadJobs } = jobs
  useEffect(() => { if (!anyActive) return; const t = window.setInterval(reloadJobs, 5000); return () => window.clearInterval(t) }, [anyActive, reloadJobs])
  const onStarted = useCallback((id: string) => { setSelected(id); reloadJobs() }, [reloadJobs])
  const onDeleted = useCallback(() => { setSelected(null); reloadJobs() }, [reloadJobs])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="flex items-center gap-2 text-2xl font-semibold text-white"><FlaskConical className="h-6 w-6 text-brand-300" />AI model test lab</h1>
          <p className="text-sm text-slate-400">Test the deepfake detectors on offline images, videos and audio. Nothing here touches customer sessions or officer reviews.</p></div>
        <Pill tone="cyan"><ShieldCheck className="h-3 w-3" />Developer only</Pill>
      </div>
      {models.error && !status ? <ErrorBox message={models.error} onRetry={models.reload} /> : !status ? <Loading /> : (<>
        <ModelHealth status={status} onChange={setStatus} />
        <NewTestPanel models={status} onStarted={onStarted} />
      </>)}
      <div className="grid gap-6 xl:grid-cols-[18rem,1fr]">
        <Card className="h-fit !p-4">
          <SectionTitle right={<button className={btnGhost} aria-label="Refresh test jobs" onClick={reloadJobs} disabled={jobs.refreshing}>{jobs.refreshing ? <Spinner /> : <RefreshCw className="h-4 w-4" />}</button>}>Test jobs</SectionTitle>
          {jobs.error && !jobs.data && <ErrorBox message={jobs.error} onRetry={reloadJobs} />}
          {jobs.data && jobs.data.items.length === 0 && <Empty title="No tests yet" hint="Upload a file or pick a dataset above." />}
          <ul className="space-y-1">{jobs.data?.items.map((j) => (
            <li key={j.id}><button onClick={() => setSelected(j.id)} aria-current={selected === j.id} className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${selected === j.id ? 'border-brand-400/50 bg-brand-400/10' : 'border-transparent hover:bg-white/5'}`}>
              <span className="flex items-center justify-between gap-2"><span className="truncate text-slate-200">{j.name}</span><Pill tone={JOB_TONE[j.status]}>{j.status}</Pill></span>
              <span className="text-xs text-slate-500">{j.finished_items}/{j.total_items} · {fmtTime(j.created_at)}</span></button></li>))}</ul>
        </Card>
        <div>{selected ? <JobView key={selected} jobId={selected} onDeleted={onDeleted} onChanged={reloadJobs} /> : <Card><Empty title="Select a test job" hint="Its progress, metrics and results appear here." /></Card>}</div>
      </div>
    </div>
  )
}
