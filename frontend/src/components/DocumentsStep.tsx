import { useState } from "react";
import { CheckCircle2, FileText, Lock, UploadCloud } from "lucide-react";
import { service } from "../features/services";
import type { DocProblem, DocType } from "../types";
import { Card, ErrorBox, Spinner, btnPrimary, inputCls } from "./ui";

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

function DocCard({
  type,
  vals,
  setVal,
  file,
  setFile,
  problems,
  done,
}: {
  type: DocType;
  vals: Record<string, string>;
  setVal: (k: string, v: string) => void;
  file?: File;
  setFile: (f?: File) => void;
  problems: DocProblem[];
  done: boolean;
}) {
  const spec = SPECS[type];
  const for_ = (k: string) => problems.filter((p) => p.field === k);
  return (
    <Card className={done ? "border-emerald-400/20" : ""}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 font-medium text-white">
            <FileText className="h-4 w-4 text-brand-400" />
            {spec.title}
          </h3>
          <p className="text-xs text-slate-500">{spec.blurb}</p>
        </div>
        {done && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            Received
          </span>
        )}
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
        <div className="mt-3">
          <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-white/15 bg-ink-950/40 px-4 py-3 text-sm text-slate-300 transition-colors hover:border-brand-400/50">
            <UploadCloud className="h-5 w-5 shrink-0 text-brand-400" />
            <span className="min-w-0 flex-1 truncate">
              {file
                ? file.name
                : "Choose a clear photo or PDF (JPEG, PNG or PDF, up to 8 MB)"}
            </span>
            <input
              type="file"
              accept="image/jpeg,image/png,application/pdf"
              className="sr-only"
              onChange={(e) => setFile(e.target.files?.[0])}
            />
          </label>
          {for_("file").map((p) => (
            <span
              key={p.code}
              role="alert"
              className="mt-1 block text-xs text-red-300"
            >
              {p.message}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Step 2 of the customer flow: upload the KYC documents. The live camera and microphone step only unlocks once the
 *  server has accepted them. Files are analysed in memory and never stored. */
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
  const [problems, setProblems] = useState<Record<string, DocProblem[]>>({});
  const [received, setReceived] = useState<Set<string>>(new Set());
  const [missing, setMissing] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const setVal = (t: string) => (k: string, v: string) =>
    setVals((s) => ({ ...s, [t]: { ...s[t], [k]: v } }));
  const touched = (t: string) =>
    Object.values(vals[t] ?? {}).some((v) => v.trim()) || Boolean(files[t]);
  const toSend = (): DocType[] => [
    "applicant",
    "pan",
    ovd,
    ...(["address_proof", "cancelled_cheque"] as DocType[]).filter(touched),
  ];

  console.log(vals);
  const submit = async () => {
    setBusy(true);
    setErr(null);
    setMissing([]);
    try {
      const next: Record<string, DocProblem[]> = {};
      const ok = new Set<string>();
      for (const t of toSend()) {
        const r = await service.uploadDocument(
          sessionId,
          t,
          vals[t] ?? {},
          SPECS[t].file ? files[t] : undefined,
        );
        next[t] = r.problems;
        if (r.accepted) ok.add(t);
      }
      setProblems(next);
      setReceived(ok);
      if (
        Object.values(next).some((p) => p.some((x) => x.severity !== "warning"))
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
        by[t] = [...(by[t] ?? []), p];
      });
      setProblems(by);
      setMissing(res.missing);
      setErr(res.message);
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(false);
    }
  };

  const label = (m: string) =>
    m === "identity_document"
      ? "an identity document (Aadhaar, passport, driving licence or voter ID)"
      : (SPECS[m as DocType]?.title ?? m);
  return (
    <div className="space-y-4">
      <Card className="flex items-start gap-3 !p-4">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />
        <p className="text-sm text-slate-400">
          Your documents are checked while you wait and are{" "}
          <span className="text-slate-200">not stored</span>: only masked
          numbers and the result of the checks are kept for the reviewing
          officer. This is a format and consistency check, not a lookup in a
          government database.
        </p>
      </Card>
      <DocCard
        type="applicant"
        vals={vals.applicant ?? {}}
        setVal={setVal("applicant")}
        setFile={() => undefined}
        problems={problems.applicant ?? []}
        done={received.has("applicant")}
      />
      <DocCard
        type="pan"
        vals={vals.pan ?? {}}
        setVal={setVal("pan")}
        file={files.pan}
        setFile={(f) => setFiles((s) => ({ ...s, pan: f }))}
        problems={problems.pan ?? []}
        done={received.has("pan")}
      />
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
              onClick={() => setOvd(t)}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${ovd === t ? "border-brand-400/60 bg-brand-400/15 text-brand-300" : "border-white/10 text-slate-400 hover:text-white"}`}
            >
              {l}
            </button>
          ))}
        </div>
      </Card>
      <DocCard
        key={ovd}
        type={ovd}
        vals={vals[ovd] ?? {}}
        setVal={setVal(ovd)}
        file={files[ovd]}
        setFile={(f) => setFiles((s) => ({ ...s, [ovd]: f }))}
        problems={problems[ovd] ?? []}
        done={received.has(ovd)}
      />
      <DocCard
        type="address_proof"
        vals={vals.address_proof ?? {}}
        setVal={setVal("address_proof")}
        file={files.address_proof}
        setFile={(f) => setFiles((s) => ({ ...s, address_proof: f }))}
        problems={problems.address_proof ?? []}
        done={received.has("address_proof")}
      />
      <DocCard
        type="cancelled_cheque"
        vals={vals.cancelled_cheque ?? {}}
        setVal={setVal("cancelled_cheque")}
        file={files.cancelled_cheque}
        setFile={(f) => setFiles((s) => ({ ...s, cancelled_cheque: f }))}
        problems={problems.cancelled_cheque ?? []}
        done={received.has("cancelled_cheque")}
      />
      {missing.length > 0 && (
        <ErrorBox message={`Still needed: ${missing.map(label).join("; ")}.`} />
      )}
      {err && <ErrorBox message={err} />}
      <div className="flex justify-end">
        <button
          className={btnPrimary}
          disabled={busy}
          onClick={() => void submit()}
        >
          {busy ? (
            <>
              <Spinner />
              Checking your documents…
            </>
          ) : (
            "Check documents and continue"
          )}
        </button>
      </div>
    </div>
  );
}
