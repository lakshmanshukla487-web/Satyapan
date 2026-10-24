import { FileCheck2Icon } from "./icons";
import type { DocFinding, OfficerDocuments } from "../../types";
import { Card, Pill, SectionTitle } from "../ui";

const LABEL: Record<string, string> = {
  applicant: "Application form",
  pan: "PAN",
  aadhaar: "Aadhaar",
  passport: "Passport",
  driving_licence: "Driving licence",
  voter_id: "Voter ID",
  address_proof: "Address proof",
  cancelled_cheque: "Cancelled cheque",
};
const FIELD: Record<string, string> = {
  name: "Name",
  dob: "Date of birth",
  year_of_birth: "Year of birth",
  pin: "PIN",
  number_masked: "Number",
  expiry_date: "Expiry",
  doc_date: "Document date",
  kind: "Kind",
  ifsc: "IFSC",
  account_last4: "Account ends",
  mobile_masked: "Mobile",
  email_masked: "Email",
  pan_holder_type: "PAN holder type",
};
const STATUS: Record<
  OfficerDocuments["status"],
  { tone: "green" | "amber" | "red" | "slate"; text: string }
> = {
  accepted: { tone: "green", text: "Consistent" },
  flagged: { tone: "amber", text: "Needs your review" },
  needs_correction: { tone: "red", text: "Customer must correct" },
  not_submitted: { tone: "slate", text: "Not submitted" },
};
const SEV: Record<
  DocFinding["severity"],
  { tone: "red" | "slate" | "green"; text: string }
> = {
  indicator: { tone: "red", text: "raised" },
  note: { tone: "slate", text: "note" },
  ok: { tone: "green", text: "fine" },
};

/** KYC documents as the officer sees them: masked numbers only, plus the cross-document findings. */
export function DocumentsPanel({
  docs,
}: {
  docs: OfficerDocuments | null | undefined;
}) {
  if (!docs) return null;
  const st = STATUS[docs.status];
  const name = (t: string) => LABEL[t] ?? t;
  return (
    <Card>
      <SectionTitle
        hint="Format, checksum and cross-document consistency. Not a lookup in UIDAI, NSDL or DigiLocker."
        right={<Pill tone={st.tone}>{st.text}</Pill>}
      >
        <span className="inline-flex items-center gap-2">
          <FileCheck2Icon />
          KYC documents
        </span>
      </SectionTitle>
      {docs.documents.length === 0 ? (
        <p className="text-sm text-slate-400">
          No documents were uploaded for this session.
        </p>
      ) : (
        <>
          {docs.findings.length > 0 && (
            <ul className="mb-4 space-y-2 text-sm">
              {docs.findings.map((f, i) => (
                <li key={`${f.code}-${i}`} className="flex items-start gap-2">
                  <Pill tone={SEV[f.severity].tone}>
                    {SEV[f.severity].text}
                  </Pill>
                  <span className="text-slate-400">
                    <span className="text-slate-200">{f.title}.</span>{" "}
                    {f.detail}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {docs.missing.length > 0 && (
            <p className="mb-3 text-sm text-amber-300">
              Missing: {docs.missing.map(name).join(", ")}
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            {docs.documents.map((d) => (
              <div
                key={d.doc_type}
                className="rounded-xl border border-white/[0.07] bg-ink-950/40 p-3"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-white">
                    {name(d.doc_type)}
                  </h3>
                  {d.problems.some((p) => p.severity !== "warning") ? (
                    <Pill tone="red">has errors</Pill>
                  ) : (
                    <Pill tone="green">valid</Pill>
                  )}
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  {Object.entries(d.info)
                    .filter(([k]) => k in FIELD)
                    .map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="text-slate-500">{FIELD[k]}</dt>
                        <dd className="truncate text-slate-200">{String(v)}</dd>
                      </div>
                    ))}
                </dl>
                {d.problems.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-red-300">
                    {d.problems.map((p) => (
                      <li key={p.code + p.field}>{p.message}</li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[11px] text-slate-500">
                  {d.file_kind !== "none"
                    ? `${d.file_kind.toUpperCase()} · sha256 ${d.file_sha256?.slice(0, 12)}… · `
                    : ""}
                  OCR:{" "}
                  {d.ocr?.state === "checked"
                    ? d.ocr.number_found === true
                      ? "number found"
                      : d.ocr.number_found === false
                        ? "number not found"
                        : "checked"
                    : d.ocr?.state === "unavailable"
                      ? "not available"
                      : "not run"}
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
