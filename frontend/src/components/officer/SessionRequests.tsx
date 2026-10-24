import { useState } from 'react'
import { Check, UserCheck, X } from 'lucide-react'
import { service } from '../../features/services'
import type { PendingSession } from '../../types'
import { Card, ErrorBox, Pill, SectionTitle, Spinner, btnDanger, btnSuccess } from '../ui'
import { fmtTime } from '../../utils/format'

const msg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')

/** Customers asking to start a verification. Nothing can happen on their side until an officer approves here. */
export function SessionRequests({ items, onChanged }: { items: PendingSession[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const act = async (id: string, what: 'approve' | 'reject') => {
    setBusy(id + what); setErr(null)
    try { if (what === 'approve') await service.approveSession(id); else await service.rejectSession(id, 'Declined by officer'); onChanged() }
    catch (e) { setErr(msg(e)); onChanged() } finally { setBusy(null) }
  }
  if (items.length === 0) return null
  return (
    <Card className="border-brand-400/40">
      <SectionTitle hint="A customer cannot upload documents, take a photo or start the camera until you approve their request." right={<Pill tone="cyan"><UserCheck className="h-3 w-3" />{items.length} asking</Pill>}>Verification requests</SectionTitle>
      <ul className="space-y-2">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.07] p-3">
            <div><p className="font-medium text-white">{r.customer ?? 'Customer'}</p><p className="text-xs text-slate-500">Asked {fmtTime(r.createdAt)} · <span className="font-mono">{r.id.slice(0, 8)}…</span></p></div>
            <div className="flex gap-2">
              <button className={btnSuccess} disabled={busy !== null} onClick={() => void act(r.id, 'approve')}>{busy === r.id + 'approve' ? <Spinner /> : <Check className="h-4 w-4" />}Approve</button>
              <button className={btnDanger} disabled={busy !== null} onClick={() => void act(r.id, 'reject')}>{busy === r.id + 'reject' ? <Spinner /> : <X className="h-4 w-4" />}Decline</button>
            </div>
          </li>))}
      </ul>
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
    </Card>
  )
}
