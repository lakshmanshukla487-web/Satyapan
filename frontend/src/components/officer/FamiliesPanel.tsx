import type { Coverage, Family, FamilyStatus } from '../../types'
import { Card, Pill, SectionTitle } from '../ui'

const TONE: Record<FamilyStatus, 'green' | 'amber' | 'red' | 'slate'> = { green: 'green', amber: 'amber', red: 'red', grey: 'slate' }
const WORD: Record<FamilyStatus, string> = { green: 'GREEN', amber: 'AMBER', red: 'RED', grey: 'GREY' }

/** Every evidence family with its own colour, judged over the whole session, plus what is still missing for GREEN. */
export function FamiliesPanel({ families, coverage, missing, overall }: { families?: Family[]; coverage?: Coverage | null; missing?: string[]; overall?: string }) {
  if (!families?.length) return null
  return (
    <Card>
      <SectionTitle hint="Each check is judged over the whole session, not one moment. A check only counts as green when it positively confirmed authenticity.">Checks by colour</SectionTitle>
      {overall && <p className="mb-3 text-sm text-slate-300">{overall}</p>}
      <ul className="grid gap-2 md:grid-cols-2">
        {families.map((f) => (
          <li key={f.id} className="rounded-xl border border-white/[0.07] p-3">
            <div className="flex items-center justify-between gap-2"><span className="font-medium text-white">{f.label}</span><Pill tone={TONE[f.status]}>{WORD[f.status]}</Pill></div>
            <p className="mt-1 text-xs text-slate-500">{f.samples} sample{f.samples === 1 ? '' : 's'}{f.score !== null && f.score !== undefined ? ` · score ${f.score.toFixed(2)}` : ''}{f.positive ? ' · positively confirmed' : ''}</p>
            {f.explain && <p className="mt-1 text-sm text-slate-400">{f.explain}</p>}
          </li>))}
      </ul>
      {coverage && <p className="mt-3 text-xs text-slate-500">Video coverage of the session: {Math.round(coverage.fraction * 100)}% of {coverage.windows} time windows{coverage.ok ? '' : ' (below the level needed for GREEN)'}.</p>}
      {missing?.length ? <div className="mt-3 border-t border-white/[0.06] pt-3"><p className="text-xs uppercase tracking-wider text-slate-500">Still needed for GREEN</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">{missing.map((m) => <li key={m}>{m}</li>)}</ul></div> : null}
    </Card>
  )
}
