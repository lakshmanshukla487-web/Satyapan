"""KYC document workflow: upload one document at a time, then submit; the cross-document check runs on submit."""
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.runtime import get_runtime
from apps.core.validation import sniff, sniff_kind
from apps.documents import ocr as ocr_mod
from apps.documents.logic.crosscheck import cross_check
from apps.documents.logic.validators import ALL_FIELD_NAMES, FIELDS, FILE_REQUIRED, OVD_TYPES, check_document
from apps.documents.models import DocumentCheck, KycDocument
from apps.evidence.services import append_event
from apps.realtime.events import publish
from apps.signals.services import run_detectors

FACE_DOCS = {"aadhaar", "pan", "passport", "driving_licence", "voter_id"}  # documents that carry a photo of the holder
CUSTOMER_STATUS = {"accepted": "accepted", "flagged": "accepted", "needs_correction": "needs_correction"}  # a flag is never shown to the customer


def id_hash(doc_type: str, number: str) -> str:
    """Keyed hash (not reversible without SECRET_KEY) so the same ID number can be recognised across sessions."""
    return hmac.new(settings.SECRET_KEY.encode(), f"{doc_type}:{number}".encode(), hashlib.sha256).hexdigest()


def clean_input(data) -> dict:
    """Only the known fields, as short strings."""
    return {k: str(data.get(k))[:100] for k in ALL_FIELD_NAMES if data.get(k) is not None}


def _clear_derived(s, doc_type: str) -> int:
    """Forget everything that was derived from the PREVIOUS file of this document type, so a replaced or removed file can never
    be reused: the face embedding taken from the document photo, and the provenance results of the old file (kept in the
    evidence history, but marked superseded so the decision engine and the officer's signal cards ignore them).
    Returns the number of superseded provenance results. Must run inside the caller's transaction."""
    from apps.biometrics.models import Observation  # lazy: biometrics depends on documents
    from apps.signals.models import DetectorSignal
    Observation.objects.filter(session=s, kind="doc_face", data__doc_type=doc_type).delete()
    n = 0
    for sig in DetectorSignal.objects.filter(session=s, detector_name="provenance"):
        d = sig.details or {}
        if d.get("doc_type") == doc_type and not d.get("superseded"):
            sig.details = {**d, "superseded": True, "superseded_at": timezone.now().isoformat()}
            sig.save(update_fields=["details"])
            n += 1
    return n


def process_upload(s, doc_type: str, data: dict, file_bytes: bytes | None) -> tuple[KycDocument, list[dict]]:
    cfg = get_runtime().settings
    fields, number, problems = check_document(doc_type, data)
    sha, kind, ocr_result = "", "none", {"state": "not_run"}
    if doc_type in FILE_REQUIRED:
        if file_bytes is None:
            problems.append({"code": "MISSING_FILE", "field": "file", "severity": "error", "message": "Upload a clear photo or PDF of this document."})
        else:
            sniff(file_bytes, "document")  # content, not file name; raises 415 for anything else
            sha, kind = hashlib.sha256(file_bytes).hexdigest(), sniff_kind(file_bytes)
            if kind != "pdf" and cfg.enable_document_ocr:
                ocr_result = ocr_mod.check_image(file_bytes, number, fields.get("name"))
    with transaction.atomic():
        previous = KycDocument.objects.filter(session=s, doc_type=doc_type).values_list("file_sha256", flat=True).first()
        superseded = _clear_derived(s, doc_type)  # results of the replaced file must never be reused
        doc, _ = KycDocument.objects.update_or_create(session=s, doc_type=doc_type, defaults={
            "info": fields, "problems": problems, "id_hash": id_hash(doc_type, number) if number else "", "file_sha256": sha, "file_kind": kind, "ocr": ocr_result})
        DocumentCheck.objects.filter(session=s).delete()  # any change means the documents must be submitted again
        ev = {"doc_type": doc_type, "file_sha256": sha, "problems": [p["code"] for p in problems]}
        if previous is not None:
            ev.update(replaced=True, previous_file_sha256=previous or None, superseded_results=superseded)
        append_event(s.id, "document.uploaded", ev)
    if file_bytes is not None and kind != "none":
        run_detectors(s, ["provenance"], file_bytes, [], extra_details={"doc_type": doc_type, "file_sha256": sha})  # family 6; a no-op if disabled
        if kind != "pdf" and doc_type in FACE_DOCS:
            try:  # the face printed on the document, kept as an embedding only
                from apps.biometrics.services import record_document_face
                from apps.core.media import decode_image
                import numpy as np
                record_document_face(get_runtime(), s, doc_type, np.asarray(decode_image(file_bytes, cfg.max_image_dimension)))
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger("satyapan").warning("document face step skipped: %s", type(e).__name__)
    publish(s.id, "document.uploaded", {"doc_type": doc_type, "problems": len(problems)})
    return doc, problems


def remove_document(s, doc_type: str) -> dict:
    """The customer takes a document back (wrong file, wrong document type, an optional document they no longer want to give).
    Files are never stored, so there is no file to delete: what is removed is everything kept ABOUT the document (the sanitised
    fields, the masked number and keyed hash, the file's SHA-256, the OCR result, the face embedding from its photo) plus the
    last document check, which is now out of date. The removal itself is recorded in the evidence chain (type and the old
    file's hash only). Idempotent: removing a document that is not there reports removed=false."""
    with transaction.atomic():
        doc = KycDocument.objects.select_for_update().filter(session=s, doc_type=doc_type).first()
        if doc is None:
            return {"doc_type": doc_type, "removed": False}
        old_sha = doc.file_sha256
        superseded = _clear_derived(s, doc_type)
        doc.delete()
        DocumentCheck.objects.filter(session=s).delete()  # the documents must be submitted (checked) again
        append_event(s.id, "document.removed", {"doc_type": doc_type, "file_sha256": old_sha or None, "superseded_results": superseded})
    publish(s.id, "document.removed", {"doc_type": doc_type})
    return {"doc_type": doc_type, "removed": True}


def _missing(docs: dict) -> list[str]:
    out = [t for t in ("applicant", "pan") if t not in docs]
    if not any(t in docs for t in OVD_TYPES):
        out.append("identity_document")  # one of: aadhaar, passport, driving_licence, voter_id
    return out


def _reuse_findings(s, docs: dict) -> list[dict]:
    out = []
    for t, d in docs.items():
        if d.id_hash and KycDocument.objects.filter(id_hash=d.id_hash).exclude(session=s).exclude(session__owner_id=s.owner_id).exists():
            out.append({"code": "ID_REUSED_BY_OTHER_CUSTOMER", "severity": "note", "title": "ID number used by another customer account",
                        "detail": f"The ID number on this {t.replace('_', ' ')} was also submitted by a different customer account. This can be innocent (a relative's account, a re-registration); check for duplicates.", "docs": [t]})
    return out


def submit_documents(s) -> tuple[DocumentCheck, list[dict], list[str]]:
    docs = {d.doc_type: d for d in KycDocument.objects.filter(session=s)}
    missing = _missing(docs)
    blocking = [{"doc_type": t, "field": p["field"], "code": p["code"], "message": p["message"]} for t, d in docs.items() for p in d.problems if p["severity"] == "error"]
    if missing or blocking:
        status, findings = "needs_correction", []
    else:
        findings = cross_check({t: {**d.info, "file_sha256": d.file_sha256, "ocr": d.ocr} for t, d in docs.items()}) + _reuse_findings(s, docs)
        status = "flagged" if any(f["severity"] == "indicator" for f in findings) else "accepted"
    with transaction.atomic():
        check, _ = DocumentCheck.objects.update_or_create(session=s, defaults={"status": status, "checked_at": timezone.now(),
                                                                                 "summary": {"findings": findings, "missing": missing, "blocking": blocking}})
        append_event(s.id, "documents.checked", {"status": status, "findings": [f["code"] for f in findings], "missing": missing})
    publish(s.id, "documents.checked", {"status": status})
    return check, blocking, missing


def reasons_for_session(s) -> list[dict]:
    """Cross-document findings as decision-engine reasons (severity indicator counts as one category: 'documents')."""
    out: list[dict] = []
    try:
        from apps.biometrics.services import document_face_reasons  # the face printed on a document vs the customer's start photo
        out += document_face_reasons(s)
    except Exception:  # noqa: BLE001  (a face-model problem must never break the decision)
        pass
    check = DocumentCheck.objects.filter(session=s).first()
    if check is None:
        return out
    return [{"code": f["code"], "severity": f["severity"], "category": "documents", "title": f["title"], "detail": f["detail"], "evidence": {"docs": f["docs"]}}
            for f in check.summary.get("findings", [])] + out


def document_summary(s) -> dict:
    """Officer/report/evidence summary. Masked numbers and codes only: no images, no full ID numbers."""
    check = DocumentCheck.objects.filter(session=s).first()
    docs = KycDocument.objects.filter(session=s).order_by("created_at")
    return {"status": check.status if check else ("not_submitted" if not docs else "not_checked"),
            "documents": [{"doc_type": d.doc_type, "number_masked": d.info.get("number_masked"), "problems": [p["code"] for p in d.problems], "file_sha256": d.file_sha256 or None,
                           "file_kind": d.file_kind, "ocr_state": (d.ocr or {}).get("state")} for d in docs],
            "findings": check.summary.get("findings", []) if check else [], "missing": check.summary.get("missing", []) if check else []}


def customer_view(s) -> dict:
    """What the customer may see: what they can fix. Cross-document findings are never shown (neutral by design)."""
    check = DocumentCheck.objects.filter(session=s).first()
    docs = KycDocument.objects.filter(session=s)
    return {"documents": [{"doc_type": d.doc_type, "accepted": not any(p["severity"] == "error" for p in d.problems),
                           "problems": [p for p in d.problems], "has_file": bool(d.file_sha256), "file_kind": d.file_kind,
                           "updated_at": d.updated_at} for d in docs],
            "status": CUSTOMER_STATUS[check.status] if check else "not_submitted",
            "required": {"always": ["applicant", "pan"], "one_of": list(OVD_TYPES), "optional": ["address_proof", "cancelled_cheque"]}}


def officer_view(s) -> dict:
    check = DocumentCheck.objects.filter(session=s).first()
    return {"status": check.status if check else "not_submitted", "checked_at": check.checked_at if check else None,
            "findings": check.summary.get("findings", []) if check else [], "missing": check.summary.get("missing", []) if check else [],
            "documents": [{"doc_type": d.doc_type, "info": d.info, "problems": d.problems, "ocr": d.ocr, "file_sha256": d.file_sha256 or None, "file_kind": d.file_kind,
                           "updated_at": d.updated_at} for d in KycDocument.objects.filter(session=s).order_by("created_at")]}
