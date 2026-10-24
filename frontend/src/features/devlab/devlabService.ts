import { env } from '../../config/env'
import { api, ApiError } from '../../services/apiClient'
import { endpoints as ep } from '../../services/endpoints'
import { downloadFile } from '../realService'
import type { DevDatasets, DevItem, DevJob, DevJobDetail, DevJobOptions, DevLabel, DevMedia, DevModelsStatus } from '../../types/devlab'

const needsBackend = () => { throw new ApiError('The model test lab runs the real detectors, so it needs the real backend (VITE_USE_MOCKS=false).', null, 'MOCK_MODE') }

/** Developer model test lab. There is no mock version on purpose: it must never show simulated model results. */
export const devlab = {
  models: () => (env.useMocks ? needsBackend() : api<DevModelsStatus>(ep.devModels, undefined, { retries: 1 })),
  checkModel: (name: string) => api<DevModelsStatus>(ep.devModelCheck(name), { method: 'POST' }, { timeoutMs: 300_000 }),
  datasets: () => (env.useMocks ? needsBackend() : api<DevDatasets>(ep.devDatasets, undefined, { retries: 1 })),
  jobs: () => (env.useMocks ? needsBackend() : api<{ items: DevJob[]; usage: { jobs: number; bytes: number } }>(ep.devJobs, undefined, { background: true, retries: 1 })),
  createUploadJob: (name: string, options: DevJobOptions) => api<DevJob>(ep.devJobs, { method: 'POST', body: JSON.stringify({ source: 'upload', name, ...options }) }),
  createDatasetJob: (dataset: string, mediaTypes: DevMedia[], limit: number, name: string, options: DevJobOptions) =>
    api<DevJob>(ep.devJobs, { method: 'POST', body: JSON.stringify({ source: 'dataset', dataset, media_types: mediaTypes, limit, name, ...options }) }),
  uploadItem: (jobId: string, file: File, label: DevLabel, signal?: AbortSignal) => {
    const f = new FormData()
    f.append('file', file, file.name)
    f.append('label', label)
    // No automatic retry: a lost answer could mean the file was already added. The uploader retries only refusals (429) itself.
    return api<DevItem>(ep.devJobItems(jobId), { method: 'POST', body: f, signal }, { timeoutMs: 180_000 })
  },
  start: (jobId: string) => api<DevJob>(ep.devJobStart(jobId), { method: 'POST' }),
  cancel: (jobId: string) => api<DevJob>(ep.devJobCancel(jobId), { method: 'POST' }),
  remove: (jobId: string) => api<{ deleted: boolean }>(ep.devJobDelete(jobId), { method: 'POST' }),
  detail: (jobId: string) => api<DevJobDetail>(ep.devJob(jobId), undefined, { background: true, retries: 1 }),
  item: (jobId: string, itemId: string) => api<DevItem>(ep.devJobItem(jobId, itemId), undefined, { retries: 1 }),
  exportResults: (jobId: string, fmt: 'csv' | 'json') => downloadFile(ep.devJobExport(jobId, fmt), `satyapan-devlab-${jobId.slice(0, 8)}.${fmt}`),
}
