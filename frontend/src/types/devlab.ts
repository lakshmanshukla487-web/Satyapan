// Developer model test lab (GET/POST /api/v1/devlab/...). Field names follow the backend.
export type DevMedia = 'image' | 'video' | 'audio'
export type DevLabel = '' | 'real' | 'fake'
export interface DevWeights { location: string | null; present: boolean; file: string | null; size_bytes?: number; config_present?: boolean; hint?: string }
export interface DevDetector {
  name: string; label: string; media_types: DevMedia[]; enabled: boolean; state: 'loaded' | 'unavailable' | 'not_loaded' | 'disabled'
  inference: 'available' | 'unavailable' | 'not_loaded' | 'disabled'; error_code: string | null; load_problem?: { missing?: string[]; mismatched?: string[]; unexpected?: string[] } | null
  model_id: string | null; model_version: string; weights: DevWeights; threshold: number | null; score_kind: string | null; score_meaning: string; video_method?: string
}
export interface DevLimits { max_upload_mb: number; max_items_per_job: number; max_job_mb: number; max_video_seconds: number; max_audio_seconds: number; video_frames_default: number; max_video_frames: number; retention_hours: number; max_image_dimension: number }
export interface DevModelsStatus { detectors: DevDetector[]; dependencies: Record<string, boolean>; detector_for_media: Record<DevMedia, string>; limits: DevLimits; preload_models: boolean }
export interface DevDataset { name: string; files: number; by_media: Partial<Record<DevMedia, number>>; labelled: number; real: number; fake: number }
export interface DevDatasets { configured: boolean; available: boolean; datasets: DevDataset[] }
export type DevAggregation = 'median' | 'mean' | 'top_quarter'
export interface DevJobOptions { aggregation: DevAggregation; video_frames: number; score_low_quality: boolean }
export type DevJobStatus = 'draft' | 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
export interface DevJob {
  id: string; name: string; source: 'upload' | 'dataset'; dataset: string | null; status: DevJobStatus; options: DevJobOptions; total_items: number; total_bytes: number
  finished_items: number; counts: Record<string, number>; cancel_requested: boolean; error: string | null; created_at: string; started_at: string | null; finished_at: string | null; expires_at: string
}
export type DevItemStatus = 'queued' | 'running' | 'done' | 'low_quality' | 'unavailable' | 'error' | 'cancelled'
export interface DevItem {
  id: string; index: number; filename: string; media_type: DevMedia; file_format: string; size_bytes: number; label: DevLabel; status: DevItemStatus; detector: string; model_id: string
  model_version: string; score: number | null; score_kind: string; threshold: number | null; prediction: DevLabel; model_label: string; duration_ms: number | null
  frames_analyzed: number | null; segments_analyzed: number | null; warnings: string[]; error_code: string; correct: boolean | null; finished_at: string | null; details?: Record<string, unknown>
}
export interface DevMetrics {
  media_type: DevMedia; detector: string; samples: number; labelled: number; evaluated: number; excluded: { reason: string; text: string; count: number }[]; thresholds: number[]
  class_support: { real: number; fake: number }; available: boolean; notes: string[]
  confusion_matrix?: { labels: string[]; rows_are: string; columns_are: string; matrix: number[][] }
  true_positive?: number; false_positive?: number; true_negative?: number; false_negative?: number
  accuracy?: number | null; precision?: number | null; recall?: number | null; specificity?: number | null; f1?: number | null; balanced_accuracy?: number | null; roc_auc?: number | null
  evaluated_support?: { real: number; fake: number }
}
export interface DevSummary { total: number; finished: number; by_status: Record<string, number>; by_media: Record<string, { count: number; scored: number; predicted_fake: number; predicted_real: number; mean_score: number | null; mean_duration_ms: number | null }> }
export interface DevJobDetail { job: DevJob; items: DevItem[]; summary: DevSummary; metrics: DevMetrics[] }
