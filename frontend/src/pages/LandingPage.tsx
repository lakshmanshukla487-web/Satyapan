import { Link } from 'react-router-dom'
import { Activity, ArrowRight, FileCheck2, Fingerprint, HeartPulse, ListChecks, Mic, ScanFace, ShieldCheck, UserCheck, Video } from 'lucide-react'
import { btnGhost, btnPrimary, Card } from '../components/ui'
import { useAuth } from '../features/auth/AuthContext'

const families = [
  { icon: Activity, t: 'Pipeline integrity', d: 'Is the camera real? Virtual-camera names and unnaturally regular frame timing are checked.' },
  { icon: ListChecks, t: 'Challenge-response', d: 'Random prompts, hidden from the customer until an officer releases them, defeat pre-recorded replays.' },
  { icon: Video, t: 'Audio-video consistency', d: 'Do the lips and the voice belong together? A synchronisation model scores it.' },
  { icon: Mic, t: 'Voice anti-spoofing', d: 'A speech model scores whether the voice may be synthetic or replayed.' },
  { icon: HeartPulse, t: 'Pulse (supporting)', d: 'A faint pulse in the face colour is measured. It supports a decision and never decides alone.' },
  { icon: Fingerprint, t: 'Provenance (supporting)', d: 'Document metadata is read for editing traces. Again supporting only.' },
]
const flow = [
  { icon: FileCheck2, t: 'Documents first', d: 'The customer uploads the documents needed to open an account. Formats, checksums and cross-document consistency are checked before any camera is switched on.' },
  { icon: ScanFace, t: 'Live check', d: 'Camera and microphone start only after the documents pass. Challenges are generated but held back.' },
  { icon: UserCheck, t: 'Officer in control', d: 'An officer approves each challenge, sees the evidence live, and can end the session at any moment.' },
]

export default function LandingPage() {
  const { user } = useAuth()
  return (
    <div className="space-y-20">
      <section className="relative overflow-hidden rounded-3xl border border-white/[0.07] bg-gradient-to-br from-ink-800 via-ink-900 to-ink-950 px-6 py-16 shadow-card md:px-14 md:py-24">
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand-400/20 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 left-1/3 h-96 w-96 rounded-full bg-brand-indigo/20 blur-3xl" />
        <div className="relative max-w-3xl space-y-6 animate-fadeUp">
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-400/30 bg-brand-400/10 px-3 py-1 text-xs font-medium text-brand-300"><ShieldCheck className="h-3.5 w-3.5" />Live V-CIP deepfake co-pilot</span>
          <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight text-white md:text-6xl">Know whether a video KYC call can be trusted <span className="bg-gradient-to-r from-brand-300 to-brand-indigo bg-clip-text text-transparent">before money moves.</span></h1>
          <p className="max-w-2xl text-lg text-slate-400">Satyapan checks the documents, then gathers independent signals about the live audio and video, and shows a human officer the reasons behind every recommendation. The officer stays in charge throughout.</p>
          <div className="flex flex-wrap gap-3 pt-2">
            {!user && <><Link to="/login" className={btnPrimary}>Sign in<ArrowRight className="h-4 w-4" /></Link><Link to="/register" className={btnGhost}>Create customer account</Link></>}
            {user?.role === 'customer' && <><Link to="/verify" className={btnPrimary}>Start verification<ArrowRight className="h-4 w-4" /></Link><Link to="/dashboard" className={btnGhost}>My dashboard</Link></>}
            {user?.role === 'officer' && <Link to="/officer" className={btnPrimary}>Open review console<ArrowRight className="h-4 w-4" /></Link>}
          </div>
        </div>
      </section>

      <section aria-label="How it works" className="space-y-6">
        <div className="max-w-2xl"><h2 className="text-2xl font-semibold text-white">One flow, three safeguards</h2><p className="mt-1 text-slate-400">Documents, then live signals, then a person. Each step has to pass before the next begins.</p></div>
        <div className="grid gap-4 md:grid-cols-3">
          {flow.map(({ icon: I, t, d }, i) => (
            <Card key={t} className="relative"><span className="absolute right-4 top-3 text-5xl font-semibold text-white/[0.04]">{i + 1}</span>
              <span className="mb-3 grid h-10 w-10 place-items-center rounded-xl bg-brand-400/10 text-brand-300"><I className="h-5 w-5" /></span>
              <h3 className="font-medium text-white">{t}</h3><p className="mt-1 text-sm text-slate-400">{d}</p></Card>))}
        </div>
      </section>

      <section aria-label="Evidence families" className="space-y-6">
        <div className="max-w-2xl"><h2 className="text-2xl font-semibold text-white">Six families of evidence</h2><p className="mt-1 text-slate-400">No single detector decides. Signals are combined by fixed, published rules, and gaps are reported as gaps, never as suspicion.</p></div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {families.map(({ icon: I, t, d }) => <Card key={t} className="transition-colors hover:border-brand-400/30"><I className="mb-3 h-5 w-5 text-brand-400" /><h3 className="font-medium text-white">{t}</h3><p className="mt-1 text-sm text-slate-400">{d}</p></Card>)}
        </div>
      </section>

      <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-200">Satyapan assists human review and does not independently establish fraud. Scores are model outputs, not calibrated probabilities of fraud. Document checks cover format, checksum and consistency; they are not a lookup in government databases.</p>
    </div>
  )
}
