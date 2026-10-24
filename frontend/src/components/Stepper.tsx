import { Check } from "lucide-react";
/** Progress through the customer flow. `current` is the index of the active step; earlier steps show a tick. */
export function Stepper({
  steps,
  current,
}: {
  steps: string[];
  current: number;
}) {
  return (
    <ol className="flex items-center gap-2" aria-label="Progress">
      {steps.map((label, i) => {
        const done = i < current,
          active = i === current;
        return (
          <li
            key={label}
            className="flex flex-1 items-center gap-2"
            aria-current={active ? "step" : undefined}
          >
            <span
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-semibold transition-colors ${done ? "border-emerald-400/60 bg-emerald-400/15 text-emerald-300" : active ? "border-brand-400 bg-brand-400/15 text-brand-300 shadow-glow" : "border-white/10 text-slate-500"}`}
            >
              {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span
              className={`hidden text-sm sm:inline ${active ? "font-medium text-white" : done ? "text-slate-300" : "text-slate-500"}`}
            >
              {label}
            </span>
            {i < steps.length - 1 && (
              <span
                className={`h-px flex-1 ${done ? "bg-emerald-400/40" : "bg-white/10"}`}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
