import type { Challenge, DetectorSignal, EvidencePacket, Quality, RiskTier, SessionEvent, SessionStatus, SignalStatus, VerificationSession } from '../types'
// ALL DATA HERE IS SIMULATED. No detector or model produced these values.
const base = Date.parse('2026-10-17T06:00:00Z')
const iso = (min: number) => new Date(base + min * 60000).toISOString()
export function mockHash(seed: string): string { // placeholder, NOT a real SHA-256
  let h = 2166136261; let out = ''
  for (let i = 0; i < 64; i++) { h = Math.imul(h ^ (seed.charCodeAt(i % seed.length) + i), 16777619); out += (h >>> 0).toString(16).padStart(8, '0').slice(-1) }
  return out
}
const sig = (id: string, name: string, model: string, optional: boolean, status: SignalStatus, score: number | null, quality: Quality | null, t: number | null, explanation: string): DetectorSignal =>
  ({ id, name, model, optional, status, score, quality, timestamp: t === null ? null : iso(t), explanation })
const ch = (id: string, type: Challenge['type'], prompt: string, status: Challenge['status'], t: number | null): Challenge => ({ id, type, prompt, status, completedAt: t === null ? null : iso(t) })
function events(sid: string, start: number, extra: string[]): SessionEvent[] {
  const msgs = ['Session created', 'Consent recorded', 'Capture started', ...extra, 'Capture ended']
  let prev: string | null = null
  return msgs.map((message, i) => { const hash = mockHash(`${sid}-${i}-${message}`); const e: SessionEvent = { id: `${sid}-e${i}`, type: 'event', timestamp: iso(start + i), message, hash, prevHash: prev }; prev = hash; return e })
}
interface Def { n: number; start: number; status: SessionStatus; tier: RiskTier; scenario: string; rec: string; reasons: string[]; signals: DetectorSignal[]; challenges: Challenge[]; ev: string[] }
const defs: Def[] = [
  { n: 1001, start: 0, status: 'reviewed', tier: 'GREEN', scenario: 'Genuine-looking session (simulated)', rec: 'No configured signals triggered. Proceed with standard review.',
    reasons: ['All challenges passed.', 'No detector flagged this session.', 'Capture quality was good for audio and video.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'available', 0.08, 'good', 4, 'Score below the review threshold configured for this demo.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'available', 0.05, 'good', 4, 'Landmark motion consistent with requested head turn.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'available', 0.11, 'good', 5, 'Score below the review threshold.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'not_run', null, null, null, 'Optional detector was not enabled.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'available', 0.1, 'fair', 5, 'Lip/audio offset within expected range.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 4 8 1 7', 'passed', 3), ch('c2', 'head_turn', 'Turn your head slowly to the left', 'passed', 4)], ev: ['Challenge c1 passed', 'Challenge c2 passed', 'Signals recorded'] },
  { n: 1002, start: 20, status: 'awaiting_review', tier: 'RED', scenario: 'Replay challenge failure (simulated)', rec: 'Escalate for manual review. Challenge response did not match the request.',
    reasons: ['Head-turn challenge failed: no matching landmark motion.', 'Digits spoken did not match the displayed digits.', 'Pattern is consistent with pre-recorded media, pending human review.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'available', 0.31, 'good', 24, 'Below threshold.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'flagged', 0.92, 'good', 24, 'Requested motion not observed.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'available', 0.28, 'good', 25, 'Below threshold.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'not_run', null, null, null, 'Optional detector was not enabled.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'not_run', null, null, null, 'Optional detector was not enabled.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 2 9 5 0', 'failed', 23), ch('c2', 'head_turn', 'Turn your head slowly to the right', 'failed', 24)], ev: ['Challenge c1 failed', 'Challenge c2 failed', 'Face signal flagged'] },
  { n: 1003, start: 45, status: 'awaiting_review', tier: 'RED', scenario: 'Multiple suspicious signals (simulated)', rec: 'Escalate for manual review. Several independent signals were flagged.',
    reasons: ['Audio anti-spoofing score exceeded the review threshold.', 'Visual classifier score exceeded the review threshold.', 'Audio-video sync offset was outside the expected range.', 'Scores are model outputs, not calibrated probabilities of fraud.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'flagged', 0.87, 'good', 49, 'Score above review threshold.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'available', 0.2, 'good', 49, 'Challenge motion observed.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'flagged', 0.79, 'fair', 50, 'Score above review threshold.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'flagged', 0.74, 'fair', 50, 'Agrees with ViT; both are model outputs only.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'flagged', 0.69, 'fair', 51, 'Offset larger than configured tolerance.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 7 3 6 1', 'passed', 48), ch('c2', 'blink', 'Blink twice', 'passed', 49)], ev: ['Challenges passed', 'Audio signal flagged', 'Visual signals flagged', 'Sync signal flagged'] },
  { n: 1004, start: 70, status: 'awaiting_review', tier: 'GREY', scenario: 'Poor lighting / audio: insufficient evidence (simulated)', rec: 'Insufficient evidence. Ask the customer to retry in better conditions.',
    reasons: ['Low light reduced face landmark confidence.', 'Background noise made audio analysis unreliable.', 'No conclusion can be drawn from this session.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'low_quality', null, 'poor', 73, 'Noise level too high for a reliable score.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'low_quality', null, 'poor', 73, 'Face not reliably detected in low light.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'low_quality', 0.4, 'poor', 74, 'Score shown but input quality was poor.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'not_run', null, null, null, 'Optional detector was not enabled.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'not_run', null, null, null, 'Optional detector was not enabled.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 1 1 4 8', 'unavailable', null), ch('c2', 'head_turn', 'Turn your head slowly to the left', 'unavailable', null)], ev: ['Quality warning: low light', 'Quality warning: audio noise'] },
  { n: 1005, start: 95, status: 'awaiting_review', tier: 'AMBER', scenario: 'Unavailable detector (simulated)', rec: 'Review recommended. One detector was unavailable, so coverage is partial.',
    reasons: ['Visual classifier was mildly above threshold.', 'Xception detector was unavailable for this session.', 'Remaining signals were within range.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'available', 0.22, 'good', 98, 'Below threshold.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'available', 0.12, 'good', 98, 'Challenge motion observed.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'flagged', 0.58, 'good', 99, 'Slightly above review threshold.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'unavailable', null, null, null, 'Detector service did not respond.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'not_run', null, null, null, 'Optional detector was not enabled.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 6 0 2 9', 'passed', 97), ch('c2', 'head_turn', 'Turn your head slowly to the right', 'passed', 98)], ev: ['Challenges passed', 'ViT signal flagged', 'Xception unavailable'] },
  { n: 1006, start: 120, status: 'in_progress', tier: 'GREY', scenario: 'Session still in progress (simulated)', rec: 'Awaiting more evidence. Capture has not finished.',
    reasons: ['Session is still running.', 'Signals have not been produced yet.'],
    signals: [sig('audio', 'Audio anti-spoofing', 'Wav2Vec2 XLS-R', false, 'not_run', null, null, null, 'Waiting for audio.'), sig('face', 'Face landmarks / challenge-response', 'MediaPipe', false, 'not_run', null, null, null, 'Waiting for video.'), sig('vit', 'Visual deepfake classification', 'ViT', false, 'not_run', null, null, null, 'Waiting for video.'), sig('xception', 'Alternative visual classifier', 'Xception', true, 'not_run', null, null, null, 'Optional detector was not enabled.'), sig('sync', 'Audio-video synchronization', 'SyncNet', true, 'not_run', null, null, null, 'Optional detector was not enabled.')],
    challenges: [ch('c1', 'digits', 'Read aloud: 3 5 8 2', 'in_progress', null), ch('c2', 'blink', 'Blink twice', 'pending', null)], ev: ['Challenge c1 started'] },
]
export const mockSessions: VerificationSession[] = defs.map((d) => {
  const id = `SAT-${d.n}`
  return { id, startedAt: iso(d.start), status: d.status, tier: d.tier, recommendation: d.rec, reasons: d.reasons, signals: d.signals, challenges: d.challenges, events: events(id, d.start, d.ev), scenario: d.scenario, simulated: true }
})
export function mockEvidence(s: VerificationSession): EvidencePacket {
  return { sessionId: s.id, generatedAt: new Date().toISOString(), mock: true, hashAlgorithm: 'SHA-256', chainStatus: 'present', events: s.events }
}
