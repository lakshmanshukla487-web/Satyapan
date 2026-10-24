import { env } from '../config/env'
import { ApiError } from '../services/apiClient'
import { realService } from './realService'
import { mockEvidence, mockSessions } from '../mocks/mockSessions'
import type { ApprovalStatus, Challenge, ChallengeKind, CreatedSession, CustomerDocuments, DocumentRemoveResult, OfficerDashboard, PendingSession, ReferenceResult, RtcConfig, DocumentSubmitResult, DocumentUploadResult, EvidencePacket, EvidenceVerificationResult, IntegrityProbe, OfficerDocuments, PendingApproval, Reason, SessionPart, SessionReport, SessionSummary, VerificationSession } from '../types'

export interface SatyapanService {
  listSessions(): Promise<VerificationSession[]>  // officers: every session, with risk detail (5 requests per session: avoid on hot paths)
  getOfficerDashboard(opts?: { background?: boolean }): Promise<OfficerDashboard>  // officers: the whole review console in one request
  refreshSession(id: string, parts: SessionPart[], current: VerificationSession): Promise<VerificationSession>  // only the parts that changed
  listMySessions(): Promise<SessionSummary[]>  // customers: only their own, without any risk outcome
  getSession(id: string): Promise<VerificationSession>
  createSession(): Promise<CreatedSession>
  recordConsent(id: string): Promise<void>  // consent only; the live step is started separately, after the documents
  startSession(id: string): Promise<void>  // needs consent and (when enabled) checked documents
  uploadDocument(id: string, docType: string, fields: Record<string, string>, file?: File): Promise<DocumentUploadResult>
  submitDocuments(id: string): Promise<DocumentSubmitResult>
  removeDocument(id: string, docType: string): Promise<DocumentRemoveResult>  // take back a wrong document (only before the live check)
  getMyDocuments(id: string): Promise<CustomerDocuments>  // customer: what is on the server and what needs fixing
  sendIntegrityProbe(id: string, probe: IntegrityProbe): Promise<void>
  sendPulse(id: string, fps: number, rgb: number[][]): Promise<void>
  currentChallenge(id: string): Promise<Challenge | null>  // customer polling fallback for the approval workflow
  // officer actions
  listPendingApprovals(): Promise<PendingApproval[]>
  approveChallenge(id: string, challengeId: string): Promise<void>
  regenerateChallenge(id: string, challengeId: string, kind?: ChallengeKind): Promise<void>
  issueChallengeAsOfficer(id: string, kind?: ChallengeKind): Promise<void>
  terminateSession(id: string, reason: string): Promise<void>
  finishSession(id: string): Promise<void>  // officer: the live check is over
  getDocuments(id: string): Promise<OfficerDocuments | null>
  getReport(id: string): Promise<SessionReport>  // officers only
  getEvidence(id: string): Promise<EvidencePacket>
  verifyEvidence(raw: string): Promise<EvidenceVerificationResult>
  issueChallenge(id: string): Promise<Challenge>
  submitChallenge(id: string, challengeId: string, measured: Record<string, number | string | null>): Promise<Challenge>
  uploadAudio(id: string, wav: Blob): Promise<void>
  uploadFrame(id: string, jpg: Blob, challengeId?: string): Promise<void>
  // v4: approval before a session, start photo, eye scan, lip-sync clip, live call, report download
  getMySession(id: string): Promise<{ id: string; status: string; approval: ApprovalStatus }>
  uploadReferencePhoto(id: string, jpg: Blob): Promise<ReferenceResult>
  submitEyeScan(id: string, challengeId: string, frames: Blob[]): Promise<void>
  submitPhrase(id: string, challengeId: string, wav: Blob, spokenText?: string): Promise<Challenge>  // the server transcribes the recording
  uploadAvSync(id: string, frames: Blob[], times: number[], wav: Blob): Promise<void>
  listPendingSessions(): Promise<PendingSession[]>
  approveSession(id: string, note?: string): Promise<void>
  rejectSession(id: string, note?: string): Promise<void>
  setAutoApprove(id: string, enabled: boolean): Promise<void>
  getRtcConfig(): Promise<RtcConfig>
  downloadReport(id: string, format: 'pdf' | 'html' | 'json'): Promise<void>
  completeSession(id: string): Promise<void>
  cancelSession(id: string): Promise<void>
}
const wait = (ms = 400) => new Promise((r) => setTimeout(r, ms))

/** Frontend-demo challenge generator. In production the backend supplies challenges. */
export function demoChallenges(): Challenge[] {
  const digits = Array.from({ length: 4 }, () => Math.floor(Math.random() * 10)).join(' ')
  const dir = Math.random() < 0.5 ? 'left' : 'right'
  return [
    { id: 'c1', type: 'digits', prompt: `Read aloud: ${digits}`, status: 'pending', completedAt: null },
    { id: 'c2', type: 'head_turn', prompt: `Turn your head slowly to the ${dir}`, status: 'pending', completedAt: null },
    { id: 'c3', type: 'blink', prompt: 'Blink twice', status: 'pending', completedAt: null },
  ]
}

/** Mock mode only: builds a report from simulated session data. Nothing here comes from a real detector. */
function mockReport(s: VerificationSession): SessionReport {
  const sev = (t: string): Reason['severity'] => (s.tier === 'GREEN' ? 'ok' : t === 'RED' || t === 'AMBER' ? 'indicator' : 'missing')
  const done = s.challenges.filter((c) => c.status === 'passed').length, failed = s.challenges.filter((c) => c.status === 'failed').length
  return {
    report_version: 'mock', generated_at: new Date().toISOString(), snapshot: 'generated_now',
    session: { id: s.id, customer: s.customer ?? null, status: s.status, created_at: s.startedAt, started_at: s.startedAt, completed_at: null, duration_seconds: null, consent_given: true, consent_timestamp: s.startedAt, policy_version: 'mock' },
    outcome: { risk_level: s.tier, headline: `${s.tier}: ${s.recommendation}`, summary: s.recommendation, rule: 'mock', rule_text: 'Simulated scenario; no policy was run.', indicators: [], evidence_completeness: 'simulated', human_review_required: true },
    reasons: s.reasons.map((r, i) => ({ code: 'MOCK', severity: sev(s.tier), category: 'simulated', title: `Reason ${i + 1}`, detail: r, evidence: {} })),
    next_steps: ['This is a simulated session. Run the real backend (VITE_USE_MOCKS=false) to see real reasons and next steps.'],
    challenges: s.challenges.map((c, i) => ({ number: i + 1, type: c.type, text: c.prompt, result: c.status, reason: null, measured: {}, issued_at: s.startedAt })),
    challenge_summary: { total: s.challenges.length, passed: done, failed, unmeasured: s.challenges.length - done - failed },
    detectors: s.signals.map((x) => ({ detector: x.id, label: x.name, status: x.status, samples: x.score === null ? 0 : 1, usable_samples: x.score === null ? 0 : 1, median_score: x.score, highest_score: x.score, threshold: null, flagged: x.status === 'flagged', error_code: null })),
    timeline: s.events.map((e) => ({ time: e.timestamp, event: e.message, detail: '' })),
    evidence_integrity: { events_checked: s.events.length, chain_valid: true, note: 'Simulated.' },
    limitations: ['All data is simulated and was not produced by a detector.'], integrity: { report_sha256: 'simulated', matches_evidence_chain: null },
  }
}

const mockService: SatyapanService = {
  async getReport(id) { return mockReport(await this.getSession(id)) },
  async listSessions() { await wait(); return mockSessions },
  async getOfficerDashboard(): Promise<OfficerDashboard> {
    await wait()
    return { sessions: mockSessions.map((x) => ({ id: x.id, customer: x.customer ?? null, status: x.status, backendStatus: x.backendStatus ?? 'completed', approval: x.approval ?? 'not_required', startedAt: x.startedAt,
      tier: x.tier, recommendation: x.recommendation, documentsStatus: x.documents?.status ?? 'not_submitted', signalsOk: x.signals.filter((g) => g.status === 'available' || g.status === 'flagged').length, signalsTotal: x.signals.length })),
      total: mockSessions.length, pendingApprovals: [], pendingRequests: [], simulated: true,
      activity: mockSessions.flatMap((x) => x.events.map((e) => ({ id: e.id, sessionId: x.id, type: e.message, timestamp: e.timestamp }))).sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 8) }
  },
  async refreshSession(id) { return this.getSession(id) },
  async removeDocument(_id, docType): Promise<DocumentRemoveResult> { await wait(150); return { doc_type: docType, removed: true, status: 'not_submitted' } },
  async getMyDocuments(): Promise<CustomerDocuments> { return { documents: [], status: 'not_submitted' } },
  async listMySessions() { await wait(); return mockSessions.slice(0, 3).map((x) => ({ id: x.id, startedAt: x.startedAt, status: x.status, approval: 'not_required' as const })) },
  async getSession(id) { await wait(); const s = mockSessions.find((x) => x.id === id); if (!s) throw new ApiError(`Session ${id} was not found.`, 404); return s },
  async createSession() { await wait(); return { sessionId: `SAT-DEMO-${Date.now().toString(36).toUpperCase()}`, challenges: demoChallenges() } },
  async recordConsent() { await wait(150) },
  async startSession() { await wait(150) },
  async uploadDocument(_id, docType): Promise<DocumentUploadResult> { await wait(200); return { doc_type: docType, accepted: true, problems: [] } },
  async submitDocuments(): Promise<DocumentSubmitResult> { await wait(300); return { status: 'accepted', problems: [], missing: [], message: 'Demo mode: documents are not analysed.' } },
  async sendIntegrityProbe() { /* mock mode: nothing is sent */ },
  async sendPulse() { /* mock mode: nothing is sent */ },
  async currentChallenge() { return null },
  async listPendingApprovals() { return [] },
  async approveChallenge() { throw new ApiError('The approval workflow needs the real backend (VITE_USE_MOCKS=false).', null) },
  async regenerateChallenge() { throw new ApiError('The approval workflow needs the real backend (VITE_USE_MOCKS=false).', null) },
  async issueChallengeAsOfficer() { throw new ApiError('The approval workflow needs the real backend (VITE_USE_MOCKS=false).', null) },
  async terminateSession() { throw new ApiError('Terminating a session needs the real backend (VITE_USE_MOCKS=false).', null) },
  async finishSession() { throw new ApiError('Finishing a session needs the real backend (VITE_USE_MOCKS=false).', null) },
  async getDocuments() { return null },
  async issueChallenge(): Promise<Challenge> { throw new ApiError('Challenges are generated in the browser in mock mode.', null) },
  async submitChallenge(): Promise<Challenge> { throw new ApiError('Challenge results are simulated in mock mode.', null) },
  async uploadAudio() { /* mock mode: nothing is uploaded */ },
  async uploadFrame() { /* mock mode: nothing is uploaded */ },
  async getMySession(id) { return { id, status: 'ready', approval: 'approved' } },
  async uploadReferencePhoto(): Promise<ReferenceResult> { await wait(300); return { accepted: true, face_check: 'ok', iris_check: 'ok', issues: [] } },
  async submitEyeScan() { /* mock mode */ },
  async submitPhrase(): Promise<Challenge> { throw new ApiError('Challenge results are simulated in mock mode.', null) },
  async uploadAvSync() { /* mock mode */ },
  async listPendingSessions() { return [] },
  async approveSession() { throw new ApiError('Approvals need the real backend (VITE_USE_MOCKS=false).', null) },
  async rejectSession() { throw new ApiError('Approvals need the real backend (VITE_USE_MOCKS=false).', null) },
  async setAutoApprove() { throw new ApiError('Approvals need the real backend (VITE_USE_MOCKS=false).', null) },
  async getRtcConfig(): Promise<RtcConfig> { return { enabled: false, iceServers: [], relayConfigured: false } },
  async downloadReport() { throw new ApiError('Report download needs the real backend (VITE_USE_MOCKS=false).', null) },
  async completeSession() { await wait(150) },
  async cancelSession() { /* nothing to cancel */ },
  async getEvidence(id) { return mockEvidence(await this.getSession(id)) },
  async verifyEvidence(raw) {
    await wait()
    let p: Partial<EvidencePacket>
    try { p = JSON.parse(raw) as Partial<EvidencePacket> } catch { return { state: 'error', simulated: true, message: 'The input is not valid JSON.' } }
    if (!p.sessionId || !Array.isArray(p.events)) return { state: 'error', simulated: true, message: 'Missing sessionId or events array.' }
    const ev = p.events
    if (p.chainStatus === 'unavailable' || ev.every((e) => !e.hash)) return { state: 'unavailable', simulated: true, message: 'No hashes are present in this packet.' }
    const broken = ev.some((e, i) => i > 0 && e.prevHash !== ev[i - 1].hash)
    return broken
      ? { state: 'invalid', simulated: true, message: 'Simulated: a previous-hash reference does not match the preceding event. No cryptographic check was run.' }
      : { state: 'valid', simulated: true, message: 'Simulated: chain links are consistent. No cryptographic check was run.' }
  },
}
export const service: SatyapanService = env.useMocks ? mockService : realService
