import { api, ApiError } from '../services/apiClient'
import { getToken } from '../services/tokenStore'
import { env } from '../config/env'
import { endpoints as ep } from '../services/endpoints'
import type { SatyapanService } from './services'
import type { ApprovalStatus, PendingSession, ReferenceResult, RtcConfig, Challenge, ChallengeKind, Coverage, CustomerDocuments, DashboardSession, DetectorSignal, DocumentRemoveResult, DocumentSubmitResult, Family, DocumentUploadResult, EvidencePacket, EvidenceVerificationResult, IntegrityProbe, OfficerDashboard, OfficerDocuments, PendingApproval, Reason, RiskTier, SessionEvent, SessionPart, SessionReport, SessionStatus, VerificationSession, WsEvent } from '../types'

interface BSession { id: string; customer?: string | null; status: string; started_at: string | null; created_at: string; termination_reason?: string; approval_status?: ApprovalStatus; challenge_auto_approve?: boolean }
interface BSignal { detector_name: string; status: string; score: number | null; threshold: number | null; error_code: string | null; created_at: string }
interface BRecommendation { risk_level: RiskTier; summary: string; reasons: string[]; reason_details?: Reason[]; headline?: string; next_steps?: string[]; families?: Family[]; coverage?: Coverage | null; overall_explain?: string; missing_for_green?: string[] }
interface BAnalysis { signals: BSignal[]; recommendation: BRecommendation }
// While a challenge waits for an officer the customer's copy has no type and no text, so both are optional.
interface BChallenge { id: string; session_id?: string; challenge_type?: string; challenge_text?: string; status: string; result?: string | null; issued_at?: string; expires_at?: string; sequence?: number; verification?: string | null; reason?: string | null; approval_status?: string }
interface BEvent { seq: number; event_type: string; timestamp: string; payload: Record<string, unknown>; previous_hash: string; event_hash: string }
interface BDashboard {
  sessions: { id: string; customer: string | null; status: string; approval_status: ApprovalStatus; created_at: string; started_at: string | null; tier: RiskTier; summary: string; documents_status: DashboardSession['documentsStatus']; signals_ok: number; signals_total: number; termination_reason?: string }[]
  total: number; pending_approvals: { challenge: BChallenge; session: { id: string; customer: string | null } }[]; pending_requests: { id: string; customer: string | null; created_at: string }[]
  activity: { session_id: string; seq: number; event_type: string; timestamp: string }[]
}

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
const EVENT_TAIL = 200  // the workspace shows the newest events; the full chain is on the evidence page

function toSignal(slot: (typeof SLOTS)[number], s?: BSignal): DetectorSignal {
  const base = { id: slot.id, name: slot.name, model: slot.model, optional: slot.optional }
  if (!s) return { ...base, status: 'not_run', score: null, quality: null, timestamp: null, explanation: 'No result yet.' }
  const flagged = s.status === 'ok' && s.score !== null && s.threshold !== null && s.score >= s.threshold
  const status = s.status === 'low_quality' ? 'low_quality' : s.status === 'ok' ? (flagged ? 'flagged' : 'available') : 'unavailable'
  const explanation = s.error_code ? `Reason code: ${s.error_code}` : s.score === null ? 'Measurement only; no spoof score.' : 'Uncalibrated model score compared with a demo threshold, not a probability of fraud.'
  return { ...base, status, score: s.score, quality: s.status === 'low_quality' ? 'poor' : null, timestamp: s.created_at, explanation }
}
const toEvent = (sid: string) => (e: BEvent): SessionEvent => ({ id: `${sid}-e${e.seq}`, type: e.event_type, timestamp: e.timestamp, message: e.event_type, hash: e.event_hash, prevHash: e.previous_hash })
export const toChallenge = (c: BChallenge): Challenge => ({
  id: c.id, type: (c.challenge_type ?? '').startsWith('head') ? 'head_turn' : c.challenge_type === 'blink' ? 'blink' : c.challenge_type === 'eye_scan' ? 'eye_scan' : 'digits', prompt: c.challenge_text ?? '', completedAt: null,
  kind: c.challenge_type as ChallengeKind | undefined,
  status: c.status === 'awaiting_approval' ? 'awaiting_approval' : c.status === 'issued' ? 'in_progress' : c.status === 'expired' ? 'unavailable' : c.result == null ? 'done' : (c.result as Challenge['status']),
  sessionId: c.session_id, sequence: c.sequence, issuedAt: c.issued_at, expiresAt: c.expires_at, result: c.result, verification: c.verification, reason: c.reason, approvalStatus: c.approval_status,
})

/* ---------------------------------------------------------------------------------------------------------------- session parts */
const fromCore = (s: BSession): Partial<VerificationSession> => ({ id: s.id, customer: s.customer ?? undefined, startedAt: s.started_at ?? s.created_at, status: STATUS[s.status] ?? 'in_progress',
  approval: s.approval_status, autoApprove: s.challenge_auto_approve, backendStatus: s.status, terminationReason: s.termination_reason || undefined })
const fromRecommendation = (r: BRecommendation): Partial<VerificationSession> => ({ tier: r.risk_level, recommendation: r.summary, reasons: r.reasons, reasonDetails: r.reason_details, headline: r.headline,
  nextSteps: r.next_steps, families: r.families, coverage: r.coverage, overallExplain: r.overall_explain, missingForGreen: r.missing_for_green })
const fromAnalysis = (a: BAnalysis): Partial<VerificationSession> => {
  const by = new Map(a.signals.map((x) => [x.detector_name, x]))
  return { ...fromRecommendation(a.recommendation), signals: SLOTS.map((sl) => toSignal(sl, by.get(sl.key))) }
}

async function fetchPart(id: string, part: SessionPart, background: boolean): Promise<Partial<VerificationSession>> {
  const o = { background, retries: 1 }
  switch (part) {
    case 'core': return fromCore(await api<BSession>(ep.session(id), undefined, o))
    case 'analysis': return fromAnalysis(await api<BAnalysis>(ep.analysis(id), undefined, o))
    case 'challenges': return { challenges: (await api<BChallenge[]>(ep.challenges(id), undefined, o)).map(toChallenge) }
    case 'events': return { events: (await api<{ events: BEvent[] }>(ep.evidenceTail(id, EVENT_TAIL), undefined, o)).events.map(toEvent(id)) }
    case 'documents': return { documents: await api<OfficerDocuments>(ep.documents(id), undefined, o).catch(() => null) }
  }
}

async function load(id: string): Promise<VerificationSession> {
  const parts = await Promise.all((['core', 'analysis', 'challenges', 'events', 'documents'] as SessionPart[]).map((p) => fetchPart(id, p, false)))
  return { id, startedAt: '', status: 'in_progress', tier: 'GREY', recommendation: '', reasons: [], signals: [], challenges: [], events: [], scenario: 'Live backend session', simulated: false, ...Object.assign({}, ...parts) } as VerificationSession
}

/** Applies an officer-socket event that already CARRIES the new state, so no request is needed: the live risk recommendation
 *  (risk.updated) and one detector result (signal.updated). Returns null when the event needs a refetch instead. */
export function applyLiveEvent(cur: VerificationSession, e: WsEvent): VerificationSession | null {
  if (e.event === 'risk.updated' && e.data && typeof e.data === 'object' && 'risk_level' in (e.data as object)) return { ...cur, ...fromRecommendation(e.data as BRecommendation) }
  if (e.event === 'analysis.completed' && e.data && typeof e.data === 'object' && 'risk_level' in (e.data as object)) return { ...cur, tier: (e.data as { risk_level: RiskTier }).risk_level }
  if (e.event === 'signal.updated' && e.data && typeof e.data === 'object') {
    const sig = e.data as BSignal
    const slot = SLOTS.find((x) => x.key === sig.detector_name)
    if (!slot) return cur
    return { ...cur, signals: cur.signals.map((x) => (x.id === slot.id ? toSignal(slot, sig) : x)) }
  }
  return null
}

const dashFromBackend = (d: BDashboard): OfficerDashboard => ({
  sessions: d.sessions.map((x) => ({ id: x.id, customer: x.customer, status: STATUS[x.status] ?? 'in_progress', backendStatus: x.status, approval: x.approval_status, startedAt: x.started_at ?? x.created_at, tier: x.tier,
    recommendation: x.summary, documentsStatus: x.documents_status, signalsOk: x.signals_ok, signalsTotal: x.signals_total, terminationReason: x.termination_reason || undefined })),
  total: d.total,
  pendingApprovals: d.pending_approvals.map((x) => ({ challenge: toChallenge(x.challenge), sessionId: x.session.id, customer: x.session.customer })),
  pendingRequests: d.pending_requests.map((x) => ({ id: x.id, customer: x.customer, createdAt: x.created_at })),
  activity: d.activity.map((a) => ({ id: `${a.session_id}-e${a.seq}`, sessionId: a.session_id, type: a.event_type, timestamp: a.timestamp })),
  simulated: false,
})

async function downloadFile(path: string, filename: string): Promise<void> { // a normal link cannot send the bearer token, so fetch the file and save it from memory
  let res: Response
  try { res = await fetch(env.apiBaseUrl + path, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } }) }
  catch { throw new ApiError('Cannot reach the verification service.', null) }
  if (!res.ok) { const b = (await res.json().catch(() => null)) as { error?: { message?: string } } | null; throw new ApiError(b?.error?.message ?? `Download failed (${res.status})`, res.status) }
  const url = URL.createObjectURL(await res.blob()), a = document.createElement('a')
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
export { downloadFile }

export const realService: SatyapanService = {
  async listSessions() { const p = await api<{ items: BSession[] }>(`${ep.sessions}?limit=100`); return Promise.all(p.items.map((x) => load(x.id))) },
  async getOfficerDashboard(opts) { return dashFromBackend(await api<BDashboard>(ep.officerDashboard, undefined, { background: opts?.background, retries: 1 })) },
  async listMySessions() { const p = await api<{ items: BSession[] }>(`${ep.sessions}?limit=100`, undefined, { retries: 1 }); return p.items.map((x) => ({ id: x.id, startedAt: x.started_at ?? x.created_at, status: STATUS[x.status] ?? 'in_progress', approval: x.approval_status ?? 'not_required' })) },
  getSession: load,
  async refreshSession(id, parts, cur) {
    const got = await Promise.all(parts.map((p) => fetchPart(id, p, true)))
    return { ...cur, ...Object.assign({}, ...got) }
  },
  async createSession() { const s = await api<BSession>(ep.sessions, { method: 'POST' }); return { sessionId: s.id, challenges: [], approval: s.approval_status ?? 'not_required' } },
  async recordConsent(id) { await api(ep.consent(id), { method: 'POST', body: JSON.stringify({ granted: true }) }) },
  async startSession(id) { await api(ep.start(id), { method: 'POST' }) },  // the backend refuses until the documents are checked
  async uploadDocument(id, docType, fields, file): Promise<DocumentUploadResult> {
    if (!file) return api<DocumentUploadResult>(ep.document(id, docType), { method: 'POST', body: JSON.stringify(fields) })  // the application form has no file
    const f = new FormData()
    Object.entries(fields).forEach(([k, v]) => { if (v) f.append(k, v) })
    f.append('file', file, file.name)
    return api<DocumentUploadResult>(ep.document(id, docType), { method: 'POST', body: f }, { timeoutMs: 60_000 })
  },
  removeDocument: (id, docType) => api<DocumentRemoveResult>(ep.documentRemove(id, docType), { method: 'POST' }),
  getMyDocuments: (id) => api<CustomerDocuments>(ep.documents(id), undefined, { retries: 1 }),
  submitDocuments: (id) => api<DocumentSubmitResult>(ep.documentsSubmit(id), { method: 'POST' }),
  async sendIntegrityProbe(id, probe: IntegrityProbe) { await api(ep.integrity(id), { method: 'POST', body: JSON.stringify(probe) }, { background: true }) },
  async sendPulse(id, fps, rgb) { await api(ep.pulse(id), { method: 'POST', body: JSON.stringify({ fps, rgb }) }, { background: true }) },
  async currentChallenge(id) { const r = await api<{ challenge: BChallenge | null }>(ep.challengeCurrent(id), undefined, { background: true }); return r.challenge ? toChallenge(r.challenge) : null },
  async listPendingApprovals(): Promise<PendingApproval[]> {
    const r = await api<{ items: { challenge: BChallenge; session: { id: string; customer: string | null } }[] }>(ep.pendingApprovals)
    return r.items.map((x) => ({ challenge: toChallenge(x.challenge), sessionId: x.session.id, customer: x.session.customer }))
  },
  async approveChallenge(id, cid, kind) { await api(ep.challengeApprove(id, cid), { method: 'POST', body: JSON.stringify(kind ? { type: kind } : {}) }) },
  async regenerateChallenge(id, cid, kind) { await api(ep.challengeRegenerate(id, cid), { method: 'POST', body: JSON.stringify(kind ? { type: kind } : {}) }) },
  async issueChallengeAsOfficer(id, kind) { await api(ep.challengeIssue(id), { method: 'POST', body: JSON.stringify(kind ? { type: kind } : {}) }) },
  async terminateSession(id, reason) { await api(ep.terminate(id), { method: 'POST', body: JSON.stringify({ reason }) }) },
  async finishSession(id) { await api(ep.finish(id), { method: 'POST' }) },
  getDocuments: (id) => api<OfficerDocuments>(ep.documents(id)),
  // Idempotent on the server (an open challenge is returned instead of a new one), so a lost answer may be retried safely.
  async issueChallenge(id) { return toChallenge(await api<BChallenge>(ep.challenges(id), { method: 'POST' }, { retries: 2 })) },
  async submitChallenge(id, cid, measured) { return toChallenge(await api<BChallenge>(ep.challengeResult(id, cid), { method: 'POST', body: JSON.stringify({ measured }) })) },
  async uploadAudio(id, wav) { const f = new FormData(); f.append('file', wav, 'clip.wav'); await api(ep.audio(id), { method: 'POST', body: f }, { background: true, timeoutMs: 45_000 }) },
  async uploadFrame(id, jpg, challengeId) { const f = new FormData(); f.append('file', jpg, 'frame.jpg'); if (challengeId) f.append('challenge_id', challengeId); await api(ep.frame(id), { method: 'POST', body: f }, { background: true, timeoutMs: 45_000 }) },
  async getMySession(id) { const s = await api<BSession>(ep.session(id), undefined, { background: true }); return { id: s.id, status: s.status, approval: s.approval_status ?? 'not_required' } },
  uploadReferencePhoto: async (id, jpg) => { const f = new FormData(); f.append('file', jpg, 'start.jpg'); return api<ReferenceResult>(ep.referencePhoto(id), { method: 'POST', body: f }, { timeoutMs: 60_000 }) },
  async submitPhrase(id, cid, wav, spokenText) { const f = new FormData(); f.append('file', wav, 'phrase.wav'); if (spokenText) f.append('spoken_text', spokenText); return toChallenge(await api<BChallenge>(ep.phrase(id, cid), { method: 'POST', body: f }, { timeoutMs: 60_000 })) },
  async submitEyeScan(id, cid, frames) { const f = new FormData(); frames.forEach((b, i) => f.append('file', b, `eye${i}.jpg`)); await api(ep.eyeScan(id, cid), { method: 'POST', body: f }, { timeoutMs: 60_000 }) },
  async uploadAvSync(id, frames, times, wav) { const f = new FormData(); frames.forEach((b, i) => f.append('frames', b, `f${i}.jpg`)); f.append('times', JSON.stringify(times)); f.append('audio', wav, 'clip.wav'); await api(ep.avsync(id), { method: 'POST', body: f }, { background: true, timeoutMs: 60_000 }) },
  async listPendingSessions(): Promise<PendingSession[]> {
    const p = await api<{ items: BSession[] }>(`${ep.sessions}?approval=pending&limit=50`)
    return p.items.map((x) => ({ id: x.id, customer: x.customer ?? null, createdAt: x.created_at }))
  },
  async approveSession(id, note) { await api(ep.approveSession(id), { method: 'POST', body: JSON.stringify({ note: note ?? '' }) }) },
  async rejectSession(id, note) { await api(ep.rejectSession(id), { method: 'POST', body: JSON.stringify({ reason: note ?? '' }) }) },
  async setAutoApprove(id, enabled) { await api(ep.autoApprove(id), { method: 'POST', body: JSON.stringify({ enabled }) }) },
  getRtcConfig: () => api<RtcConfig>(ep.rtcConfig, undefined, { retries: 2 }),
  downloadReport: (id, format) => downloadFile(ep.reportDownload(id, format), `satyapan-report-${id.slice(0, 8)}.${format}`),
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
