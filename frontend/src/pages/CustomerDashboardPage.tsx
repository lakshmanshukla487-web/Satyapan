import { Link } from 'react-router-dom'
import { FileText, RefreshCw, ScanFace, ShieldCheck, UserCheck } from 'lucide-react'
import { service } from '../features/services'
import { useAuth } from '../features/auth/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { Card, Empty, ErrorBox, Loading, Pill, btnGhost, btnPrimary } from '../components/ui'
import { fmtTime } from '../utils/format'
import type { SessionStatus } from '../types'

// Plain-language status. A customer never sees risk scores or the reviewer's assessment.
const label: Record<SessionStatus, { text: string; tone: 'cyan' | 'green' | 'slate' | 'amber' }> = {
  in_progress: { text: 'In progress', tone: 'cyan' },
  awaiting_review: { text: 'Submitted for officer review', tone: 'amber' },
  reviewed: { text: 'Reviewed', tone: 'green' },
  abandoned: { text: 'Not completed', tone: 'slate' },
  terminated: { text: 'Ended. We will complete it another way', tone: 'slate' },
}

export default function CustomerDashboardPage() {
  const { user } = useAuth()
  const { data, error, loading, reload } = useAsync(() => service.listMySessions(), [])
  const rows = data ?? []
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold text-white">Welcome, {user?.username}</h1><p className="text-sm text-slate-400">Your identity verification sessions.</p></div>
        <div className="flex gap-3"><button className={btnGhost} onClick={reload} disabled={loading}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button><Link to="/verify" className={btnPrimary}><ShieldCheck className="h-4 w-4" />Start new verification</Link></div>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {([[FileText, '1. Officer approval and documents', 'An officer approves your request. Then upload the documents needed to open an account in India: PAN, one proof of identity and address (Aadhaar, passport, driving licence or voter ID), and your details.'], [ScanFace, '2. Photo and live check', 'Take a close-up starting photo, then allow your camera and microphone and follow the prompts for as long as the check runs. The officer may ask to see and talk to you.'], [UserCheck, '3. Officer review', 'A person reviews the result and decides. Video and audio are analysed and not stored; only results are kept.']] as const).map(([Icon, t, d]) => (
          <Card key={t}><Icon className="mb-2 h-5 w-5 text-brand-400" /><h2 className="font-medium text-white">{t}</h2><p className="mt-1 text-sm text-slate-400">{d}</p></Card>))}
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !data ? <Loading /> : data && (
        <Card>
          <h2 className="mb-3 font-medium text-white">My sessions</h2>
          {rows.length === 0 ? <Empty title="No verifications yet" hint="Start a new verification to see it here." /> : (
            <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="p-2">Session</th><th className="p-2">Started</th><th className="p-2">Status</th></tr></thead>
              <tbody>{rows.map((s) => <tr key={s.id} className="border-t border-white/[0.07]"><td className="p-2 font-mono text-xs text-slate-300">{s.id}</td><td className="whitespace-nowrap p-2">{fmtTime(s.startedAt)}</td><td className="p-2">{s.approval === 'pending' && s.status === 'in_progress' ? <Pill tone="amber">Waiting for an officer to approve</Pill> : s.approval === 'rejected' || s.approval === 'expired' ? <Pill tone="slate">Not taken forward</Pill> : <Pill tone={label[s.status].tone}>{label[s.status].text}</Pill>}</td></tr>)}</tbody></table></div>)}
        </Card>)}
    </div>
  )
}
