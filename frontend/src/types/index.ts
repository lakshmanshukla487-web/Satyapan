export type Role = 'customer' | 'officer'
export interface User { id: number | string; username: string; role: Role }
export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected' | 'expired'
export interface SessionSummary { id: string; startedAt: string; status: SessionStatus; approval: ApprovalStatus }  // what a customer may see: no risk outcome
export type RiskTier = 'GREEN' | 'AMBER' | 'RED' | 'GREY'
export type SessionStatus = 'in_progress' | 'awaiting_review' | 'reviewed' | 'abandoned' | 'terminated'
export type ChallengeStatus = 'pending' | 'in_progress' | 'passed' | 'failed' | 'unavailable' | 'awaiting_approval' | 'done'  // 'done' = answered, result hidden from the customer
export type SignalStatus = 'available' | 'flagged' | 'unavailable' | 'low_quality' | 'not_run'
export type Quality = 'good' | 'fair' | 'poor'
export type ChallengeKind = 'head_left' | 'head_right' | 'blink' | 'phrase' | 'eye_scan'
export interface Challenge { id: string; type: 'digits' | 'head_turn' | 'blink' | 'eye_scan'; prompt: string; status: ChallengeStatus; completedAt: string | null; kind?: ChallengeKind }
export interface DetectorSignal { id: string; name: string; model: string; optional: boolean; status: SignalStatus; score: number | null; quality: Quality | null; timestamp: string | null; explanation: string }
export type ReasonSeverity = 'indicator' | 'missing' | 'note' | 'ok'
/** Why the session got its colour. indicator = counted toward the level; missing = evidence gap; note = informational; ok = supports authenticity. */
export interface Reason { code: string; severity: ReasonSeverity; category: string; title: string; detail: string; evidence: Record<string, unknown> }
export interface SessionEvent { id: string; type: string; timestamp: string; message: string; hash: string | null; prevHash: string | null }
export interface VerificationSession {
  id: string; customer?: string; startedAt: string; status: SessionStatus; tier: RiskTier; recommendation: string; reasons: string[]
  reasonDetails?: Reason[]; headline?: string; nextSteps?: string[]
  signals: DetectorSignal[]; challenges: Challenge[]; events: SessionEvent[]
  scenario: string; simulated: boolean
  /** Officer view only: the backend's own status word, why an officer ended the session, and the KYC document review. */
  backendStatus?: string; terminationReason?: string; documents?: OfficerDocuments | null
  approval?: ApprovalStatus; autoApprove?: boolean; families?: Family[]; coverage?: Coverage | null; overallExplain?: string; missingForGreen?: string[]
}
export type FamilyStatus = 'green' | 'amber' | 'red' | 'grey'
export interface Family { id: string; label: string; status: FamilyStatus; score: number | null; threshold: number | null; samples: number; usable: number; positive: boolean; explain: string }
export interface Coverage { windows: number; covered: number; fraction: number; ok: boolean }
/** Officer summary report as returned by GET /sessions/:id/report (field names follow the backend). */
export interface SessionReport {
  report_version: string; generated_at: string; snapshot: 'stored_at_completion' | 'generated_now'
  session: { id: string; customer: string | null; status: string; approval_status?: string; created_at: string; started_at: string | null; completed_at: string | null; duration_seconds: number | null; consent_given: boolean; consent_timestamp: string | null; policy_version: string }
  outcome: { risk_level: RiskTier; headline: string; summary: string; rule: string; rule_text: string; indicators: string[]; evidence_completeness: string; human_review_required: boolean }
  reasons: Reason[]; next_steps: string[]
  challenges: { number: number; type: string; text: string; result: string; reason: string | null; measured: Record<string, unknown>; issued_at: string }[]
  challenge_summary: { total: number; passed: number; failed: number; unmeasured: number }
  detectors: { detector: string; label: string; status: string; samples: number; usable_samples: number; median_score: number | null; highest_score: number | null; threshold: number | null; flagged: boolean; error_code: string | null }[]
  timeline: { time: string; event: string; detail: string }[]
  evidence_integrity: { events_checked: number; chain_valid: boolean; note: string }
  limitations: string[]
  families?: Family[]
  session_analysis?: { duration_seconds: number | null; median_response_ms: number | null; challenges_over_time: { seq: number; type: string; at_s: number; status: string; result: string | null; verification: string | null; response_ms: number | null }[] }
  identity?: { reference_photo: { uploaded: boolean; iris_usable: boolean; issues: string[] }; face_match: { samples: number; median_similarity: number | null; min_similarity: number | null; threshold: number | null }; iris_scans: { verdict: string; hamming_distance: number | null }[] }
  network?: { ips_seen: string[]; ip_check: Record<string, unknown> | null; camera_check: Record<string, unknown> | null; notes: string[] }
  plain_language?: PlainLanguage
  documents?: { status: string; documents: { doc_type: string; number_masked: string | null; problems: string[]; file_sha256: string | null; file_kind: string; ocr_state: string | null }[]; findings: DocFinding[]; missing: string[] }
  integrity: { report_sha256: string; matches_evidence_chain: boolean | null }
}
export interface PlainLanguage { overall: string; result_colour: RiskTier; colour_legend: { colour: string; meaning: string }[]; by_check: { check: string; colour: string; in_plain_words: string }[]; how_decided: string; what_to_do: string[] }
export interface EvidencePacket { sessionId: string; generatedAt: string; mock: boolean; hashAlgorithm: 'SHA-256'; chainStatus: 'present' | 'unavailable'; events: SessionEvent[]; raw?: unknown }
export interface EvidenceVerificationResult { state: 'valid' | 'invalid' | 'unavailable' | 'error'; simulated: boolean; message: string }
export interface CreatedSession { sessionId: string; challenges: Challenge[]; approval?: ApprovalStatus }
export type WsState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'
export interface WsEvent { event: string; session_id: string; timestamp: string; data: unknown }

// ---- KYC documents -------------------------------------------------------------------------------------------------
export type DocType = 'applicant' | 'pan' | 'aadhaar' | 'passport' | 'driving_licence' | 'voter_id' | 'address_proof' | 'cancelled_cheque'
export interface DocProblem { doc_type?: string; field: string; code: string; message: string; severity?: 'error' | 'warning' }
export interface DocumentUploadResult { doc_type: string; accepted: boolean; problems: DocProblem[] }
export interface DocumentSubmitResult { status: 'accepted' | 'needs_correction'; problems: DocProblem[]; missing: string[]; message: string }
export interface DocFinding { code: string; severity: 'indicator' | 'note' | 'ok'; title: string; detail: string; docs: string[] }
export interface OfficerDocument { doc_type: string; info: Record<string, unknown>; problems: DocProblem[]; ocr: { state?: string; number_found?: boolean; name_overlap?: number | null }; file_sha256: string | null; file_kind: string }
export interface OfficerDocuments { status: 'not_submitted' | 'needs_correction' | 'flagged' | 'accepted'; checked_at: string | null; findings: DocFinding[]; missing: string[]; documents: OfficerDocument[] }

// ---- officer approval workflow ---------------------------------------------------------------------------------------
export interface PendingApproval { challenge: Challenge; sessionId: string; customer: string | null }
export interface IntegrityProbe {
  camera_label: string; width: number; height: number; frame_rate: number | null; intervals_ms: number[]; webdriver: boolean
  capabilities?: string[]; video_devices?: { label: string }[]; native_get_user_media?: boolean | null; native_enumerate_devices?: boolean | null
  device_id_present?: boolean | null; webrtc_ips?: string[]; timezone?: string; tz_offset_min?: number | null
}
export interface RtcConfig { enabled: boolean; iceServers: { urls: string[]; username?: string; credential?: string }[]; relayConfigured: boolean }
export interface PendingSession { id: string; customer: string | null; createdAt: string }
export interface ReferenceResult { accepted: boolean; face_check: string; iris_check: string; issues: string[]; messages?: string[]; blocking?: string[] }
