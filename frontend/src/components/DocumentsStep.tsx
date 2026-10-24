import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Lock,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { service } from "../features/services";
import type { CustomerDocState, DocProblem, DocType } from "../types";
import {
  Card,
  ErrorBox,
  Modal,
  Spinner,
  btnDanger,
  btnGhost,
  btnPrimary,
  inputCls,
} from "./ui";

interface F {
  k: string;
  label: string;
  ph?: string;
  req?: boolean;
  options?: [string, string][];
  max?: number;
}
interface Spec {
  title: string;
  blurb: string;
  file: boolean;
  fields: F[];
}

const OVDS: [DocType, string][] = [
  ["aadhaar", "Aadhaar"],
  ["passport", "Passport"],
  ["driving_licence", "Driving licence"],
  ["voter_id", "Voter ID"],
];
const NAME = (label = "Name as on the document"): F => ({
  k: "name",
  label,
  ph: "Exactly as printed",
  req: true,
  max: 100,
});
const SPECS: Record<DocType, Spec> = {
  applicant: {
    title: "Your details",
    blurb: "What you declare on the application.",
    file: false,
    fields: [
      {
        k: "full_name",
        label: "Full name",
        ph: "As on your PAN",
        req: true,
        max: 100,
      },
      {
        k: "dob",
        label: "Date of birth",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      {
        k: "mobile",
        label: "Mobile number",
        ph: "10 digits",
        req: true,
        max: 10,
      },
      { k: "pin", label: "PIN code", ph: "6 digits", req: true, max: 6 },
      { k: "email", label: "Email (optional)", max: 100 },
    ],
  },
  pan: {
    title: "PAN card",
    blurb: "Required. Individual PAN only.",
    file: true,
    fields: [
      NAME("Name on PAN"),
      { k: "pan_number", label: "PAN", ph: "ABCDE1234F", req: true, max: 10 },
      {
        k: "dob",
        label: "Date of birth on PAN",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
    ],
  },
  aadhaar: {
    title: "Aadhaar",
    blurb: "The 12-digit number, not the 16-digit Virtual ID.",
    file: true,
    fields: [
      NAME("Name on Aadhaar"),
      {
        k: "aadhaar_number",
        label: "Aadhaar number",
        ph: "12 digits",
        req: true,
        max: 14,
      },
      {
        k: "dob",
        label: "Date of birth (if printed)",
        ph: "DD/MM/YYYY",
        max: 10,
      },
      {
        k: "year_of_birth",
        label: "Year of birth (if no full date)",
        ph: "YYYY",
        max: 4,
      },
      { k: "pin", label: "PIN code on Aadhaar", max: 6 },
    ],
  },
  passport: {
    title: "Passport",
    blurb: "Must not be expired.",
    file: true,
    fields: [
      NAME(),
      { k: "passport_number", label: "Passport number", req: true, max: 10 },
      {
        k: "dob",
        label: "Date of birth",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      {
        k: "expiry_date",
        label: "Expiry date",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      { k: "pin", label: "PIN code (optional)", max: 6 },
    ],
  },
  driving_licence: {
    title: "Driving licence",
    blurb: "Must not be expired.",
    file: true,
    fields: [
      NAME(),
      {
        k: "dl_number",
        label: "Licence number",
        ph: "PB10 20110012345",
        req: true,
        max: 20,
      },
      {
        k: "dob",
        label: "Date of birth",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      {
        k: "expiry_date",
        label: "Valid until",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      { k: "pin", label: "PIN code (optional)", max: 6 },
    ],
  },
  voter_id: {
    title: "Voter ID (EPIC)",
    blurb: "Identity and address proof.",
    file: true,
    fields: [
      NAME(),
      {
        k: "epic_number",
        label: "EPIC number",
        ph: "ABC1234567",
        req: true,
        max: 12,
      },
      {
        k: "dob",
        label: "Date of birth (optional)",
        ph: "DD/MM/YYYY",
        max: 10,
      },
      { k: "pin", label: "PIN code (optional)", max: 6 },
    ],
  },
  address_proof: {
    title: "Address proof (optional)",
    blurb: "A recent utility bill or bank statement.",
    file: true,
    fields: [
      NAME("Name on the document"),
      { k: "pin", label: "PIN code", req: true, max: 6 },
      {
        k: "doc_date",
        label: "Date on the document",
        ph: "DD/MM/YYYY",
        req: true,
        max: 10,
      },
      {
        k: "kind",
        label: "Kind",
        req: true,
        options: [
          ["electricity", "Electricity bill"],
          ["gas", "Gas bill"],
          ["water", "Water bill"],
          ["telephone", "Telephone bill"],
          ["bank_statement", "Bank statement"],
        ],
      },
    ],
  },
  cancelled_cheque: {
    title: "Cancelled cheque (optional)",
    blurb: "Only the last 4 digits of the account number are asked for.",
    file: true,
    fields: [
      NAME("Account holder name"),
      { k: "ifsc", label: "IFSC", ph: "HDFC0001234", req: true, max: 11 },
      {
        k: "account_last4",
        label: "Last 4 digits of the account number",
        req: true,
        max: 4,
      },
    ],
  },
};
const msg = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong.";
const MAX_DOC_MB = 8; // backend MAX_DOCUMENT_MB
const ALLOWED: Record<string, string> = {
  "image/jpeg": "JPEG",
  "image/png": "PNG",
  "application/pdf": "PDF",
};
const EXT: Record<string, string> = {
  jpg: "JPEG",
  jpeg: "JPEG",
  png: "PNG",
  pdf: "PDF",
};
const kindOf = (f: File) =>
  ALLOWED[f.type] ?? EXT[f.name.split(".").pop()?.toLowerCase() ?? ""] ?? null;
const fmtSize = (n: number) =>
  n >= 1024 * 1024
    ? `${(n / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(n / 1024))} KB`;
const OPTIONAL: DocType[] = ["address_proof", "cancelled_cheque"];

/** Quick checks in the browser so a wrong pick is caught at once. The server still checks the real content (never the name). */
function checkFile(f: File): string | null {
  if (!kindOf(f)) return "Only JPEG, PNG or PDF files can be used.";
  if (f.size === 0) return "That file is empty.";
  if (f.size > MAX_DOC_MB * 1024 * 1024)
    return `That file is ${fmtSize(f.size)}; the limit is ${MAX_DOC_MB} MB.`;
  return null;
}

function DocCard({
  type,
  vals,
  setVal,
  file,
  onPick,
  onClear,
  problems,
  server,
  fileError,
  busy,
  onRemoveServer,
  dirty,
}: {
  type: DocType;
  vals: Record<string, string>;
  setVal: (k: string, v: string) => void;
  file?: File;
  onPick: (f: File) => void;
  onClear: () => void;
  problems: DocProblem[];
  server?: CustomerDocState;
  fileError?: string;
  busy: boolean;
  onRemoveServer: () => void;
  dirty: boolean;
}) {
  const spec = SPECS[type];
  const input = useRef<HTMLInputElement | null>(null);
  const for_ = (k: string) => problems.filter((p) => p.field === k);
  const accepted = Boolean(server?.accepted) && !dirty;
  const pick = () => {
    if (input.current) {
      input.current.value = "";
      input.current.click();
    }
  };
  return (
    <Card className={accepted ? "border-emerald-400/20" : ""}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 font-medium text-white">
            <FileText className="h-4 w-4 text-brand-400" />
            {spec.title}
          </h3>
          <p className="text-xs text-slate-500">{spec.blurb}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {accepted && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
              <CheckCircle2 className="h-4 w-4" />
              Received
            </span>
          )}
          {server && !server.accepted && !dirty && (
            <span className="inline-flex items-center gap-1 text-xs text-red-300">
              <AlertTriangle className="h-4 w-4" />
              Needs correction
            </span>
          )}
          {dirty && server && (
            <span className="text-xs text-amber-300">
              Changed: will be sent again
            </span>
          )}
          {server && (
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-slate-400 underline hover:text-red-300 disabled:opacity-50"
              disabled={busy}
              onClick={onRemoveServer}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove submitted document
            </button>
          )}
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {spec.fields.map((f) => (
          <label key={f.k} className="block text-sm text-slate-300">
            {f.label}
            {f.req && <span className="text-red-300"> *</span>}
            {f.options ? (
              <select
                className={inputCls}
                value={vals[f.k] ?? ""}
                disabled={busy}
                onChange={(e) => setVal(f.k, e.target.value)}
              >
                <option value="">Choose…</option>
                {f.options.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={inputCls}
                value={vals[f.k] ?? ""}
                placeholder={f.ph}
                maxLength={f.max}
                disabled={busy}
                onChange={(e) => setVal(f.k, e.target.value)}
                autoComplete="off"
              />
            )}
            {for_(f.k).map((p) => (
              <span
                key={p.code + f.k}
                role="alert"
                className={`mt-1 block text-xs ${p.severity === "warning" ? "text-amber-300" : "text-red-300"}`}
              >
                {p.message}
              </span>
            ))}
          </label>
        ))}
      </div>
      {spec.file && (
        <div className="mt-3 space-y-2">
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf"
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onPick(f);
            }}
          />
          {file ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-white/15 bg-ink-950/40 px-4 py-3 text-sm">
              <FileText className="h-5 w-5 shrink-0 text-brand-400" />
              <span className="min-w-0 flex-1">
                <span
                  className="block truncate text-slate-200"
                  title={file.name}
                >
                  {file.name}
                </span>
                <span className="text-xs text-slate-500">
                  {kindOf(file)} · {fmtSize(file.size)}
                  {dirty ? " · not sent yet" : " · sent"}
                </span>
              </span>
              <button
                type="button"
                className={btnGhost}
                disabled={busy}
                onClick={pick}
              >
                <RefreshCw className="h-4 w-4" />
                Replace
              </button>
              <button
                type="button"
                className={btnGhost}
                disabled={busy}
                onClick={onClear}
                aria-label={`Remove the selected file for ${spec.title}`}
              >
                <X className="h-4 w-4" />
                Remove
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={pick}
              className="flex w-full items-center gap-3 rounded-lg border border-dashed border-white/15 bg-ink-950/40 px-4 py-3 text-left text-sm text-slate-300 transition-colors hover:border-brand-400/50 disabled:opacity-50"
            >
              <UploadCloud className="h-5 w-5 shrink-0 text-brand-400" />
              <span className="min-w-0 flex-1">
                {server?.has_file ? (
                  <>
                    A {server.file_kind.toUpperCase()} file was received earlier
                    (checked, not stored, so its name is not kept).{" "}
                    <span className="text-brand-300 underline">
                      Choose a file to replace it
                    </span>
                    .
                  </>
                ) : (
                  `Choose a clear photo or PDF (JPEG, PNG or PDF, up to ${MAX_DOC_MB} MB)`
                )}
              </span>
            </button>
          )}
          {fileError && (
            <span role="alert" className="block text-xs text-red-300">
              {fileError}
            </span>
          )}
          {for_("file").map((p) => (
            <span
              key={p.code}
              role="alert"
              className="block text-xs text-red-300"
            >
              {p.message}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Step 2 of the customer flow: upload the KYC documents. The live camera and microphone step only unlocks once the server has
 *  accepted them. Files are analysed in memory and never stored. A wrong file or a wrong document can be removed or replaced at
 *  any time until the live check starts, without starting over: only that document's results are reset. */
export function DocumentsStep({
  sessionId,
  onAccepted,
}: {
  sessionId: string;
  onAccepted: () => void;
}) {
  const [ovd, setOvd] = useState<DocType>("aadhaar");
  const [vals, setVals] = useState<Record<string, Record<string, string>>>({});
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [fileErr, setFileErr] = useState<Record<string, string | undefined>>(
    {},
  );
  const [problems, setProblems] = useState<Record<string, DocProblem[]>>({});
  const [server, setServer] = useState<Record<string, CustomerDocState>>({});
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [missing, setMissing] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<DocType | null>(null);
  const loaded = useRef(false);

  // What is already on the server (for example after going back from the photo step), so it can be kept, replaced or removed.
  useEffect(() => {
    let alive = true;
    service
      .getMyDocuments(sessionId)
      .then((r) => {
        if (!alive) return;
        const by: Record<string, CustomerDocState> = {};
        r.documents.forEach((d) => {
          by[d.doc_type] = d;
        });
        setServer(by);
        setProblems(
          Object.fromEntries(r.documents.map((d) => [d.doc_type, d.problems])),
        );
        const existingOvd = OVDS.map(([t]) => t).find((t) => by[t]);
        if (existingOvd && !loaded.current) setOvd(existingOvd);
        loaded.current = true;
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [sessionId]);

  const markDirty = (t: string) =>
    setDirty((d) => (d.has(t) ? d : new Set(d).add(t)));
  const setVal = (t: string) => (k: string, v: string) => {
    setVals((s) => ({ ...s, [t]: { ...s[t], [k]: v } }));
    markDirty(t);
  };
  const pickFile = (t: string) => (f: File) => {
    const bad = checkFile(f);
    setFileErr((s) => ({ ...s, [t]: bad ?? undefined }));
    if (bad) return; // the previous valid selection (if any) stays
    setFiles((s) => ({ ...s, [t]: f }));
    setProblems((s) => ({
      ...s,
      [t]: (s[t] ?? []).filter((p) => p.field !== "file"),
    })); // file problems belonged to the old file
    markDirty(t);
  };
  const clearFile = (t: string) => () => {
    setFiles((s) => ({ ...s, [t]: undefined }));
    setFileErr((s) => ({ ...s, [t]: undefined }));
    if (server[t]?.has_file)
      markDirty(t); // the submitted file is still on record until it is replaced or the document is removed
    else
      setDirty((d) => {
        const n = new Set(d);
        if (!Object.values(vals[t] ?? {}).some((v) => v.trim())) n.delete(t);
        return n;
      });
  };
  const touched = (t: string) =>
    Object.values(vals[t] ?? {}).some((v) => v.trim()) || Boolean(files[t]);
  const toSend = (): DocType[] => [
    "applicant",
    "pan",
    ovd,
    ...OPTIONAL.filter(touched),
  ];

  const removeServer = async (t: DocType) => {
    setBusy(`remove:${t}`);
    setErr(null);
    setNote(null);
    try {
      await service.removeDocument(sessionId, t);
      setServer((s) => {
        const n = { ...s };
        delete n[t];
        return n;
      });
      setProblems((s) => ({ ...s, [t]: [] }));
      setFiles((s) => ({ ...s, [t]: undefined }));
      setFileErr((s) => ({ ...s, [t]: undefined }));
      if (OPTIONAL.includes(t) || (t !== ovd && OVDS.some(([o]) => o === t))) {
        // not needed any more: drop the form too, so it is not sent again
        setVals((s) => ({ ...s, [t]: {} }));
        setDirty((d) => {
          const n = new Set(d);
          n.delete(t);
          return n;
        });
      } else if (Object.values(vals[t] ?? {}).some((v) => v.trim()))
        markDirty(t);
      setMissing([]);
      setNote(
        `${SPECS[t].title} was removed. Your other documents are unchanged; press “Check documents and continue” when you are ready.`,
      );
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  const submit = async () => {
    setBusy("submit");
    setErr(null);
    setNote(null);
    setMissing([]);
    try {
      const next: Record<string, DocProblem[]> = { ...problems };
      const nextServer = { ...server };
      let localProblem = false;
      for (const t of toSend()) {
        if (!dirty.has(t) && nextServer[t]) continue; // already on the server and unchanged: nothing to send
        const needsFile = SPECS[t].file;
        if (needsFile && !files[t]) {
          if (!dirty.has(t) && !nextServer[t] && !touched(t)) continue; // not filled in at all: the server reports it as missing
          next[t] = [
            ...(next[t] ?? []).filter((p) => p.field !== "file"),
            {
              field: "file",
              code: "MISSING_FILE",
              severity: "error",
              message: nextServer[t]?.has_file
                ? "Files are not kept on our servers, so a corrected document must be uploaded together with its file. Choose the file again."
                : "Upload a clear photo or PDF of this document.",
            },
          ];
          localProblem = true;
          continue;
        }
        const r = await service.uploadDocument(
          sessionId,
          t,
          vals[t] ?? {},
          needsFile ? files[t] : undefined,
        );
        next[t] = r.problems;
        nextServer[t] = {
          doc_type: t,
          accepted: r.accepted,
          problems: r.problems,
          has_file: Boolean(needsFile && files[t]),
          file_kind: files[t]
            ? (kindOf(files[t] as File) ?? "").toLowerCase()
            : "none",
        };
        setDirty((d) => {
          const n = new Set(d);
          n.delete(t);
          return n;
        });
      }
      setProblems(next);
      setServer(nextServer);
      if (
        localProblem ||
        Object.entries(next).some(
          ([t, p]) =>
            (nextServer[t] || toSend().includes(t as DocType)) &&
            p.some((x) => x.severity !== "warning"),
        )
      ) {
        setErr("Please fix the highlighted items and try again.");
        return;
      }
      const res = await service.submitDocuments(sessionId);
      if (res.status === "accepted") {
        onAccepted();
        return;
      }
      const by: Record<string, DocProblem[]> = { ...next };
      res.problems.forEach((p) => {
        const t = p.doc_type ?? "";
        by[t] = [
          ...(by[t] ?? []).filter(
            (x) => x.code !== p.code || x.field !== p.field,
          ),
          p,
        ];
      });
      setProblems(by);
      setMissing(res.missing);
      setErr(res.message);
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(null);
    }
  };

  const label = (m: string) =>
    m === "identity_document"
      ? "an identity document (Aadhaar, passport, driving licence or voter ID)"
      : (SPECS[m as DocType]?.title ?? m);
  const otherOvds = OVDS.filter(([t]) => t !== ovd && server[t]);
  const card = (t: DocType) => (
    <DocCard
      key={t}
      type={t}
      vals={vals[t] ?? {}}
      setVal={setVal(t)}
      file={files[t]}
      onPick={pickFile(t)}
      onClear={clearFile(t)}
      problems={problems[t] ?? []}
      server={server[t]}
      fileError={fileErr[t]}
      busy={busy !== null}
      onRemoveServer={() => setConfirm(t)}
      dirty={dirty.has(t)}
    />
  );
  return (
    <div className="space-y-4">
      <Card className="flex items-start gap-3 !p-4">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />
        <p className="text-sm text-slate-400">
          Your documents are checked while you wait and are{" "}
          <span className="text-slate-200">not stored</span>: only masked
          numbers and the result of the checks are kept for the reviewing
          officer. This is a format and consistency check, not a lookup in a
          government database. Picked the wrong file? Use{" "}
          <span className="text-slate-200">Replace</span> or{" "}
          <span className="text-slate-200">Remove</span>; you can correct
          documents until the live check starts.
        </p>
      </Card>
      {card("applicant")}
      {card("pan")}
      <Card className="!p-4">
        <p className="mb-2 text-sm font-medium text-white">
          Identity and address document <span className="text-red-300">*</span>
        </p>
        <div
          role="tablist"
          aria-label="Choose a document"
          className="flex flex-wrap gap-2"
        >
          {OVDS.map(([t, l]) => (
            <button
              key={t}
              role="tab"
              aria-selected={ovd === t}
              disabled={busy !== null}
              onClick={() => setOvd(t)}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${ovd === t ? "border-brand-400/60 bg-brand-400/15 text-brand-300" : "border-white/10 text-slate-400 hover:text-white"}`}
            >
              {l}
              {server[t] ? " ✓" : ""}
            </button>
          ))}
        </div>
        {otherOvds.length > 0 && (
          <div className="mt-3 space-y-1 text-xs text-slate-400">
            {otherOvds.map(([t, l]) => (
              <p key={t} className="flex flex-wrap items-center gap-2">
                You also submitted a {l}
                {server[t] && !server[t].accepted
                  ? " that needs correction"
                  : ""}
                . It is still part of your documents.
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-slate-300 underline hover:text-red-300"
                  disabled={busy !== null}
                  onClick={() => setConfirm(t)}
                >
                  <Trash2 className="h-3 w-3" />
                  Remove it
                </button>
              </p>
            ))}
          </div>
        )}
      </Card>
      {card(ovd)}
      {card("address_proof")}
      {card("cancelled_cheque")}
      {missing.length > 0 && (
        <ErrorBox message={`Still needed: ${missing.map(label).join("; ")}.`} />
      )}
      {note && (
        <p role="status" className="text-sm text-emerald-300">
          {note}
        </p>
      )}
      {err && <ErrorBox message={err} />}
      <div className="flex justify-end">
        <button
          className={btnPrimary}
          disabled={busy !== null}
          onClick={() => void submit()}
        >
          {busy === "submit" ? (
            <>
              <Spinner />
              Checking your documents…
            </>
          ) : (
            "Check documents and continue"
          )}
        </button>
      </div>
      <Modal
        open={confirm !== null}
        title="Remove this document?"
        onClose={() => {
          if (!busy) setConfirm(null);
        }}
      >
        {confirm && (
          <>
            <p className="text-sm text-slate-400">
              The {SPECS[confirm].title.toLowerCase()} you submitted, and the
              results of checking it, will be removed. Your other documents stay
              as they are.{" "}
              {OPTIONAL.includes(confirm)
                ? "This optional document will not be sent again unless you fill it in again."
                : "You will need to submit a corrected one before the live check."}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className={btnGhost}
                disabled={busy !== null}
                onClick={() => setConfirm(null)}
              >
                Keep it
              </button>
              <button
                className={btnDanger}
                disabled={busy !== null}
                onClick={() => void removeServer(confirm)}
              >
                {busy?.startsWith("remove:") ? (
                  <Spinner />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Remove
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
