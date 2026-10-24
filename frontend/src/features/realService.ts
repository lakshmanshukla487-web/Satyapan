import { api, ApiError } from '../services/apiClient'
import { getToken } from '../services/tokenStore'
import { env } from '../config/env'
import { endpoints as ep } from '../services/endpoints'
import type { SatyapanService } from './services'
import type { ApprovalStatus, PendingSession, ReferenceResult, RtcConfig, Challenge, ChallengeKind, Coverage, DetectorSignal, DocumentSubmitResult, Family, DocumentUploadResult, EvidencePacket, EvidenceVerificationResult, IntegrityProbe, OfficerDocuments, PendingApproval, Reason, RiskTier, SessionEvent, SessionReport, SessionStatus, VerificationSession } from '../types'

interface BSession { id: string; customer?: string | null; status: string; started_at: string | null; created_at: string; termination_reason?: string; approval_status?: ApprovalStatus; challenge_auto_approve?: boolean }
interface BSignal { detector_name: string; status: string; score: number | null; threshold: number | null; error_code: string | null; created_at: string }
interface BAnalysis { signals: BSignal[]; recommendation: { risk_level: RiskTier; summary: string; reasons: string[]; reason_details?: Reason[]; headline?: string; next_steps?: string[]; families?: Family[]; coverage?: Coverage | null; overall_explain?: string; missing_for_green?: string[] } }
// While a challenge waits for an officer the customer's copy has no type and no text, so both are optional.
interface BChallenge { id: string; challenge_type?: string; challenge_text?: string; status: string; result?: string | null }
interface BEvent { seq: number; event_type: string; timestamp: string; payload: Record<string, unknown>; previous_hash: string; event_hash: string }

const SLOTS = [
  { key: 'audio', id: 'audio', name: 'Audio anti-spoofing', model: 'Wav2Vec2 XLS-R', optional: false },
  { key: 'landmarks', id: 'face', name: 'Face landmarks / challenge-response', model: 'MediaPipe', optional: false },
  { key: 'vit', id: 'vit', name: 'Video deepfake classification', model: 'ViT', optional: false },
  { key: 'xception', id: 'xception', name: 'Alternative visual classifier', model: 'Xception', optional: true },
  { key: 'syncnet', id: 'sync', name: 'Lip-sync (audio-video synchronization)', model: 'SyncNet', optional: true },
  { key: 'facematch', id: 'facematch', name: 'Face match against the start photo', model: 'YuNet + SFace', optional: true },
  { key: 'eyescan', id: 'eyescan', name: 'Iris scan (close-up)', model: 'Iris code', optional: true },
  { key: 'integrity', id: 'integrity', name: 'Pipeline integrity (camera and IP)', model: 'Rule-based', optional: true },
  { key: 'pulse', id: 'pulse', name: 'Pulse (rPPG), supporting only', model: 'POS algorithm', optional: true },
  { key: 'provenance', id: 'provenance', name: 'Document provenance, supporting only', model: 'Metadata rules', optional: true },
] as const
const STATUS: Record<string, SessionStatus> = { created: 'in_progress', awaiting_consent: 'in_progress', ready: 'in_progress', running: 'in_progress', completed: 'awaiting_review', cancelled: 'abandoned', failed: 'abandoned', terminated: 'terminated' }

function toSignal(slot: (typeof SLOTS)[number], s?: BSignal): DetectorSignal {
  const base = { id: slot.id, name: slot.name, model: slot.model, optional: slot.optional }
  if (!s) return { ...base, status: 'not_run', score: null, quality: null, timestamp: null, explanation: 'No result yet.' }
  const flagged = s.status === 'ok' && s.score !== null && s.threshold !== null && s.score >= s.threshold
  const status = s.status === 'low_quality' ? 'low_quality' : s.status === 'ok' ? (flagged ? 'flagged' : 'available') : 'unavailable'
  const explanation = s.error_code ? `Reason code: ${s.error_code}` : s.score === null ? 'Measurement only; no spoof score.' : 'Uncalibrated model score compared with a demo threshold, not a probability of fraud.'
  return { ...base, status, score: s.score, quality: s.status === 'low_quality' ? 'poor' : null, timestamp: s.created_at, explanation }
}
const toEvent = (sid: string) => (e: BEvent): SessionEvent => ({ id: `${sid}-e${e.seq}`, type: e.event_type, timestamp: e.timestamp, message: e.event_type, hash: e.event_hash, prevHash: e.previous_hash })
const toChallenge = (c: BChallenge): Challenge => ({
  id: c.id, type: (c.challenge_type ?? '').startsWith('head') ? 'head_turn' : c.challenge_type === 'blink' ? 'blink' : c.challenge_type === 'eye_scan' ? 'eye_scan' : 'digits', prompt: c.challenge_text ?? '', completedAt: null,
  kind: c.challenge_type as ChallengeKind | undefined,
  status: c.status === 'awaiting_approval' ? 'awaiting_approval' : c.status === 'issued' ? 'in_progress' : c.status === 'expired' ? 'unavailable' : c.result == null ? 'done' : (c.result as Challenge['status']),
})

async function load(id: string): Promise<VerificationSession> {
  const [s, a, c, e, docs] = await Promise.all([api<BSession>(ep.session(id)), api<BAnalysis>(ep.analysis(id)), api<BChallenge[]>(ep.challenges(id)), api<{ events: BEvent[] }>(ep.evidence(id)),
    api<OfficerDocuments>(ep.documents(id)).catch(() => null)])
  const by = new Map(a.signals.map((x) => [x.detector_name, x]))
  return { id: s.id, customer: s.customer ?? undefined, startedAt: s.started_at ?? s.created_at, status: STATUS[s.status] ?? 'in_progress', tier: a.recommendation.risk_level, recommendation: a.recommendation.summary,
    reasons: a.recommendation.reasons, reasonDetails: a.recommendation.reason_details, headline: a.recommendation.headline, nextSteps: a.recommendation.next_steps, signals: SLOTS.map((sl) => toSignal(sl, by.get(sl.key))), challenges: c.map(toChallenge), approval: s.approval_status, autoApprove: s.challenge_auto_approve,
    families: a.recommendation.families, coverage: a.recommendation.coverage, overallExplain: a.recommendation.overall_explain, missingForGreen: a.recommendation.missing_for_green, events: e.events.map(toEvent(id)), scenario: 'Live backend session', simulated: false,
    backendStatus: s.status, terminationReason: s.termination_reason || undefined, documents: docs }
}

export const realService: SatyapanService = {
  async listSessions() { const p = await api<{ items: BSession[] }>(`${ep.sessions}?limit=100`); return Promise.all(p.items.map((x) => load(x.id))) },
  async listMySessions() { const p = await api<{ items: BSession[] }>(`${ep.sessions}?limit=100`); return p.items.map((x) => ({ id: x.id, startedAt: x.started_at ?? x.created_at, status: STATUS[x.status] ?? 'in_progress', approval: x.approval_status ?? 'not_required' })) },
  getSession: load,
  async createSession() { const s = await api<BSession>(ep.sessions, { method: 'POST' }); return { sessionId: s.id, challenges: [], approval: s.approval_status ?? 'not_required' } },
  async recordConsent(id) { await api(ep.consent(id), { method: 'POST', body: JSON.stringify({ granted: true }) }) },
  async startSession(id) { await api(ep.start(id), { method: 'POST' }) },  // the backend refuses until the documents are checked
  async uploadDocument(id, docType, fields, file): Promise<DocumentUploadResult> {
    if (!file) return api<DocumentUploadResult>(ep.document(id, docType), { method: 'POST', body: JSON.stringify(fields) })  // the application form has no file
    const f = new FormData()
    Object.entries(fields).forEach(([k, v]) => { if (v) f.append(k, v) })
    f.append('file', file, file.name)
    return api<DocumentUploadResult>(ep.document(id, docType), { method: 'POST', body: f })
  },
  submitDocuments: (id) => api<DocumentSubmitResult>(ep.documentsSubmit(id), { method: 'POST' }),
  async sendIntegrityProbe(id, probe: IntegrityProbe) { await api(ep.integrity(id), { method: 'POST', body: JSON.stringify(probe) }) },
  async sendPulse(id, fps, rgb) { await api(ep.pulse(id), { method: 'POST', body: JSON.stringify({ fps, rgb }) }) },
  async currentChallenge(id) { const r = await api<{ challenge: BChallenge | null }>(ep.challengeCurrent(id)); return r.challenge ? toChallenge(r.challenge) : null },
  async listPendingApprovals(): Promise<PendingApproval[]> {
    const r = await api<{ items: { challenge: BChallenge; session: { id: string; customer: string | null } }[] }>(ep.pendingApprovals)
    return r.items.map((x) => ({ challenge: toChallenge(x.challenge), sessionId: x.session.id, customer: x.session.customer }))
  },
  async approveChallenge(id, cid) { await api(ep.challengeApprove(id, cid), { method: 'POST' }) },
  async regenerateChallenge(id, cid, kind) { await api(ep.challengeRegenerate(id, cid), { method: 'POST', body: JSON.stringify(kind ? { type: kind } : {}) }) },
  async issueChallengeAsOfficer(id, kind) { await api(ep.challengeIssue(id), { method: 'POST', body: JSON.stringify(kind ? { type: kind } : {}) }) },
  async terminateSession(id, reason) { await api(ep.terminate(id), { method: 'POST', body: JSON.stringify({ reason }) }) },
  getDocuments: (id) => api<OfficerDocuments>(ep.documents(id)),
  async issueChallenge(id) { return toChallenge(await api<BChallenge>(ep.challenges(id), { method: 'POST' })) },
  async submitChallenge(id, cid, measured) { return toChallenge(await api<BChallenge>(ep.challengeResult(id, cid), { method: 'POST', body: JSON.stringify({ measured }) })) },
  async uploadAudio(id, wav) { const f = new FormData(); f.append('file', wav, 'clip.wav'); await api(ep.audio(id), { method: 'POST', body: f }) },
  async uploadFrame(id, jpg, challengeId) { const f = new FormData(); f.append('file', jpg, 'frame.jpg'); if (challengeId) f.append('challenge_id', challengeId); await api(ep.frame(id), { method: 'POST', body: f }) },
  async getMySession(id) { const s = await api<BSession>(ep.session(id)); return { id: s.id, status: s.status, approval: s.approval_status ?? 'not_required' } },
  uploadReferencePhoto: async (id, jpg) => { const f = new FormData(); f.append('file', jpg, 'start.jpg'); return api<ReferenceResult>(ep.referencePhoto(id), { method: 'POST', body: f }) },
  async submitEyeScan(id, cid, frames) { const f = new FormData(); frames.forEach((b, i) => f.append('file', b, `eye${i}.jpg`)); await api(ep.eyeScan(id, cid), { method: 'POST', body: f }) },
  async uploadAvSync(id, frames, times, wav) { const f = new FormData(); frames.forEach((b, i) => f.append('frames', b, `f${i}.jpg`)); f.append('times', JSON.stringify(times)); f.append('audio', wav, 'clip.wav'); await api(ep.avsync(id), { method: 'POST', body: f }) },
  async listPendingSessions(): Promise<PendingSession[]> {
    const p = await api<{ items: BSession[] }>(`${ep.sessions}?approval=pending&limit=50`)
    return p.items.map((x) => ({ id: x.id, customer: x.customer ?? null, createdAt: x.created_at }))
  },
  async approveSession(id, note) { await api(ep.approveSession(id), { method: 'POST', body: JSON.stringify({ note: note ?? '' }) }) },
  async rejectSession(id, note) { await api(ep.rejectSession(id), { method: 'POST', body: JSON.stringify({ reason: note ?? '' }) }) },
  async setAutoApprove(id, enabled) { await api(ep.autoApprove(id), { method: 'POST', body: JSON.stringify({ enabled }) }) },
  getRtcConfig: () => api<RtcConfig>(ep.rtcConfig),
  async downloadReport(id, format) { // a normal link cannot send the bearer token, so fetch the file and save it from memory
    let res: Response
    try { res = await fetch(env.apiBaseUrl + ep.reportDownload(id, format), { headers: { Authorization: `Bearer ${getToken() ?? ''}` } }) }
    catch { throw new ApiError('Cannot reach the verification service.', null) }
    if (!res.ok) { const b = (await res.json().catch(() => null)) as { error?: { message?: string } } | null; throw new ApiError(b?.error?.message ?? `Download failed (${res.status})`, res.status) }
    const url = URL.createObjectURL(await res.blob()), a = document.createElement('a')
    a.href = url; a.download = `satyapan-report-${id.slice(0, 8)}.${format}`; document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 5000)
  },
  async completeSession(id) { await api(ep.complete(id), { method: 'POST' }) },
  async cancelSession(id) { await api(ep.cancel(id), { method: 'POST' }) },
  getReport: (id) => api<SessionReport>(ep.report(id)),
  async getEvidence(id): Promise<EvidencePacket> {
    const raw = await api<{ generated_at: string; hash_chain: { events: BEvent[] } }>(ep.evidenceExport(id))
    return { sessionId: id, generatedAt: raw.generated_at, mock: false, hashAlgorithm: 'SHA-256', chainStatus: 'present', events: raw.hash_chain.events.map(toEvent(id)), raw }
  },
  async verifyEvidence(text): Promise<EvidenceVerificationResult> {
    let p: { session?: { id?: string }; hash_chain?: { events?: BEvent[] } }
    try { p = JSON.parse(text) } catch { return { state: 'error', simulated: false, message: 'The input is not valid JSON.' } }
    const id = p.session?.id, events = p.hash_chain?.events
    if (!id || !events) return { state: 'error', simulated: false, message: 'Paste a packet exported from the backend.' }
    const r = await api<{ valid: boolean; checked: number; first_mismatch_seq: number | null; reason: string | null; note: string }>(ep.evidenceVerify(id), { method: 'POST', body: JSON.stringify({ events }) })
    return r.valid ? { state: 'valid', simulated: false, message: `Hash chain consistent across ${r.checked} events. ${r.note}` }
      : { state: 'invalid', simulated: false, message: `First mismatch at event ${r.first_mismatch_seq}: ${r.reason}.` }
  },
}
