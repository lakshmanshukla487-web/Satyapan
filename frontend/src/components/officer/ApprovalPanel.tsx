import { useState } from "react";
import { CheckCircle2, Hourglass, RefreshCw, Send } from "lucide-react";
import { service } from "../../features/services";
import type { Challenge, ChallengeKind } from "../../types";
import {
  Card,
  ErrorBox,
  Pill,
  SectionTitle,
  Spinner,
  btnGhost,
  btnSuccess,
  inputCls,
} from "../ui";

export const KIND_LABEL: Record<ChallengeKind, string> = {
  head_left: "Turn head left",
  head_right: "Turn head right",
  blink: "Blink twice",
  phrase: "Say three words",
  eye_scan: "Close-up eye scan",
};
const msg = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong.";

/** One challenge waiting for an officer. Its text is hidden from the customer until it is approved here. */
export function PendingChallenge({
  sessionId,
  c,
  onDone,
}: {
  sessionId: string;
  c: Challenge;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "regen" | null>(null);
  const [kind, setKind] = useState<ChallengeKind | "">("");
  const [err, setErr] = useState<string | null>(null);
  const run = async (what: "approve" | "regen") => {
    setBusy(what);
    setErr(null);
    try {
      if (what === "approve") await service.approveChallenge(sessionId, c.id);
      else
        await service.regenerateChallenge(sessionId, c.id, kind || undefined);
      onDone();
    } catch (e) {
      setErr(msg(e));
      onDone();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="rounded-xl border border-amber-400/30 bg-amber-400/[0.07] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-amber-300">
            Waiting for your approval
          </p>
          <p className="mt-1 text-lg font-medium text-white">{c.prompt}</p>
          <p className="text-xs text-slate-500">
            The customer cannot see this yet.
          </p>
        </div>
        <Hourglass className="h-5 w-5 shrink-0 text-amber-300" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          className={btnSuccess}
          disabled={busy !== null}
          onClick={() => void run("approve")}
        >
          {busy === "approve" ? (
            <Spinner />
          ) : (
            <CheckCircle2 className="h-4 w-4" />
          )}
          Approve and release
        </button>
        <select
          aria-label="Type for the replacement challenge"
          className={`${inputCls} !mt-0 !w-auto`}
          value={kind}
          onChange={(e) => setKind(e.target.value as ChallengeKind | "")}
        >
          <option value="">Random type</option>
          {(Object.keys(KIND_LABEL) as ChallengeKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <button
          className={btnGhost}
          disabled={busy !== null}
          onClick={() => void run("regen")}
        >
          {busy === "regen" ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
          Regenerate
        </button>
      </div>
      {err && (
        <div className="mt-3">
          <ErrorBox message={err} />
        </div>
      )}
    </div>
  );
}

/** Approval and "run a challenge now" for one live session. */
export function ApprovalPanel({
  sessionId,
  challenges,
  live,
  autoApprove = false,
  onChanged,
}: {
  sessionId: string;
  challenges: Challenge[];
  live: boolean;
  autoApprove?: boolean;
  onChanged: () => void;
}) {
  const pending = challenges.filter((c) => c.status === "awaiting_approval");
  const active = challenges.find((c) => c.status === "in_progress");
  const [kind, setKind] = useState<ChallengeKind>("blink");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [auto, setAuto] = useState(autoApprove);
  const toggleAuto = async (v: boolean) => {
    setAuto(v);
    setErr(null);
    try {
      await service.setAutoApprove(sessionId, v);
      onChanged();
    } catch (e) {
      setAuto(!v);
      setErr(msg(e));
    }
  };
  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      await service.issueChallengeAsOfficer(sessionId, kind);
      onChanged();
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <SectionTitle
        hint="A generated challenge stays hidden from the customer until you release it."
        right={
          <Pill tone={pending.length ? "amber" : "slate"}>
            {pending.length} waiting
          </Pill>
        }
      >
        Challenge approval
      </SectionTitle>
      {live && (
        <label className="mb-3 flex cursor-pointer items-start gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            className="mt-1"
            checked={auto}
            onChange={(e) => void toggleAuto(e.target.checked)}
          />
          <span>
            Release every new challenge automatically for this session
            <span className="block text-xs text-slate-500">
              Challenges keep coming for the whole session. Leave this off if
              you want to look at each one first.
            </span>
          </span>
        </label>
      )}
      {!live && (
        <p className="text-sm text-slate-400">
          The session is not live, so there is nothing to approve.
        </p>
      )}
      {live && pending.length === 0 && (
        <p className="text-sm text-slate-400">
          {active ? (
            <>
              Released and with the customer now:{" "}
              <span className="text-slate-200">{active.prompt}</span>
            </>
          ) : (
            "No challenge is waiting. The next one appears here as soon as the customer’s page requests it."
          )}
        </p>
      )}
      <div className="space-y-3">
        {pending.map((c) => (
          <PendingChallenge
            key={c.id}
            sessionId={sessionId}
            c={c}
            onDone={onChanged}
          />
        ))}
      </div>
      {live && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4">
          <span className="text-sm text-slate-400">Run a challenge now:</span>
          <select
            aria-label="Challenge type"
            className={`${inputCls} !mt-0 !w-auto`}
            value={kind}
            onChange={(e) => setKind(e.target.value as ChallengeKind)}
          >
            {(Object.keys(KIND_LABEL) as ChallengeKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
          <button
            className={btnGhost}
            disabled={busy}
            onClick={() => void send()}
          >
            {busy ? <Spinner /> : <Send className="h-4 w-4" />}Send to customer
          </button>
        </div>
      )}
      {err && (
        <div className="mt-3">
          <ErrorBox message={err} />
        </div>
      )}
    </Card>
  );
}
