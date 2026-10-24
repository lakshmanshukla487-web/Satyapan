import { useState } from 'react'
import { Ban } from 'lucide-react'
import { service } from '../../features/services'
import { ErrorBox, Modal, Spinner, btnDanger, btnGhost, inputCls } from '../ui'

/** Officer override: end the session at any time. The customer is told, neutrally, that the check ends here. */
export function TerminateDialog({ open, sessionId, onClose, onDone }: { open: boolean; sessionId: string; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const go = async () => {
    setBusy(true); setErr(null)
    try { await service.terminateSession(sessionId, reason.trim()); setReason(''); onDone(); onClose() }
    catch (e) { setErr(e instanceof Error ? e.message : 'Could not end the session.') } finally { setBusy(false) }
  }
  return (
    <Modal open={open} title="End this session now?" onClose={onClose}>
      <p className="text-sm text-slate-400">The customer’s camera step stops immediately and they see a neutral message (no accusation). Evidence and the report are kept. This cannot be undone.</p>
      <label className="mt-4 block text-sm text-slate-300">Reason for the record (optional)
        <textarea className={`${inputCls} min-h-20`} maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: documents do not match the person on camera" /></label>
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      <div className="mt-4 flex justify-end gap-2"><button className={btnGhost} onClick={onClose} disabled={busy}>Keep session</button><button className={btnDanger} onClick={() => void go()} disabled={busy}>{busy ? <Spinner /> : <Ban className="h-4 w-4" />}End session</button></div>
    </Modal>
  )
}
