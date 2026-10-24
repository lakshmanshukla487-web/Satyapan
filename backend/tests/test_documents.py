"""KYC documents: upload, validation, cross-document verification, and the gate before the live camera/microphone step."""
from apps.documents.logic.validators import verhoeff_check_digit
from tests.conftest import ensure_user, client_for, png_bytes

S = "/api/v1/sessions"
BODY = "23456789012"
AADHAAR = BODY + verhoeff_check_digit(BODY)
APPLICANT = {"full_name": "Rahul Sharma", "dob": "15/08/1995", "mobile": "9876543210", "pin": "141001"}
PAN = {"name": "RAHUL SHARMA", "pan_number": "ABCPS1234F", "dob": "1995-08-15"}
AADH = {"name": "Rahul Sharma", "aadhaar_number": AADHAAR, "dob": "15/08/1995", "pin": "141001"}
IMG = ("doc.png", png_bytes((400, 400)), "image/png")


def consented(c):
    sid = c.post(S).json()["id"]
    assert c.post(f"{S}/{sid}/consent", json={"granted": True}).status_code == 200
    return sid


def up(c, sid, doc_type, fields, file=True):
    return c.post(f"{S}/{sid}/documents/{doc_type}", files={"file": IMG} if file else None, json=None if file else fields, fields=fields if file else None)


def upload_all(c, sid, pan=PAN, aadhaar=AADH, applicant=APPLICANT):
    assert up(c, sid, "applicant", applicant, file=False).json()["accepted"]
    assert up(c, sid, "pan", pan).json()["accepted"]
    assert up(c, sid, "aadhaar", aadhaar).json()["accepted"]


def test_start_is_blocked_until_documents_are_submitted_and_checked(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    r = c.post(f"{S}/{sid}/start")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENTS_REQUIRED"
    upload_all(c, sid)
    assert c.post(f"{S}/{sid}/start").status_code == 409                     # uploaded but not submitted yet
    sub = c.post(f"{S}/{sid}/documents/submit").json()
    assert sub["status"] == "accepted" and sub["problems"] == [] and sub["missing"] == []
    assert c.post(f"{S}/{sid}/start").status_code == 200


def test_missing_documents_and_typing_errors_need_correction(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    sub = c.post(f"{S}/{sid}/documents/submit").json()
    assert sub["status"] == "needs_correction" and set(sub["missing"]) == {"applicant", "pan", "identity_document"}
    bad = up(c, sid, "pan", {**PAN, "pan_number": "ABCDE12345"}).json()
    assert bad["accepted"] is False and bad["problems"][0]["code"] == "INVALID_PAN"
    up(c, sid, "applicant", APPLICANT, file=False)
    up(c, sid, "aadhaar", AADH)
    sub = c.post(f"{S}/{sid}/documents/submit").json()
    assert sub["status"] == "needs_correction" and sub["problems"][0]["code"] == "INVALID_PAN"
    assert c.post(f"{S}/{sid}/start").status_code == 409
    assert up(c, sid, "pan", PAN).json()["accepted"]                         # fix it, submit again
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "accepted"
    assert c.post(f"{S}/{sid}/start").status_code == 200


def test_cross_document_mismatch_is_flagged_to_the_officer_not_the_customer(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid, pan={**PAN, "name": "PRIYA VERMA", "dob": "1990-01-01"})
    sub = c.post(f"{S}/{sid}/documents/submit").json()
    assert sub["status"] == "accepted" and sub["problems"] == []              # neutral: the customer is not told
    assert c.post(f"{S}/{sid}/start").status_code == 200
    cust = c.get(f"{S}/{sid}/documents").json()
    assert cust["status"] == "accepted" and "findings" not in cust and "NAME_MISMATCH" not in str(cust)
    off = c.officer.get(f"{S}/{sid}/documents").json()
    assert off["status"] == "flagged" and {"NAME_MISMATCH", "DOB_MISMATCH"} <= {f["code"] for f in off["findings"]}
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert rec["risk_level"] == "AMBER" and "documents" in rec["indicators"]
    assert any(r["code"] == "NAME_MISMATCH" and r["category"] == "documents" for r in rec["reason_details"])


def test_consistent_documents_do_not_raise_anything(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    c.post(f"{S}/{sid}/documents/submit")
    c.post(f"{S}/{sid}/start")
    off = c.officer.get(f"{S}/{sid}/documents").json()
    assert off["status"] == "accepted" and {f["code"] for f in off["findings"]} >= {"NAME_CONSISTENT", "DOB_CONSISTENT"}
    assert "documents" not in c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]["indicators"]


def test_only_masked_numbers_are_stored_and_returned(make_client):
    from apps.documents.models import KycDocument
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    dump = str([(d.info, d.problems, d.id_hash, d.ocr) for d in KycDocument.objects.filter(session_id=sid)])
    assert AADHAAR not in dump and "ABCPS1234F" not in dump and "XXXX XXXX " + AADHAAR[-4:] in dump
    off = str(c.officer.get(f"{S}/{sid}/documents").json())
    assert AADHAAR not in off and "ABCPS1234F" not in off
    assert "XXXX XXXX " + AADHAAR[-4:] in str(c.officer.get(f"{S}/{sid}/evidence/export").json()["documents"])


def test_changing_a_document_requires_submitting_again(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    c.post(f"{S}/{sid}/documents/submit")
    up(c, sid, "pan", PAN)
    assert c.get(f"{S}/{sid}/documents").json()["status"] == "not_submitted"
    assert c.post(f"{S}/{sid}/start").status_code == 409


def test_upload_rules(make_client):
    c = make_client(require_documents=True)
    sid = c.post(S).json()["id"]
    assert up(c, sid, "pan", PAN).status_code == 403                          # consent first
    c.post(f"{S}/{sid}/consent", json={"granted": True})
    assert c.post(f"{S}/{sid}/documents/not_a_doc", json={}).status_code == 404
    gif = c.post(f"{S}/{sid}/documents/pan", files={"file": ("a.gif", b"GIF89a" + b"\0" * 50, "image/gif")}, fields=PAN)
    assert gif.status_code == 415 and gif.json()["error"]["code"] == "UNSUPPORTED_MEDIA"
    assert up(c, sid, "pan", {**PAN, "pan_number": "x" * 300}, file=True).json()["accepted"] is False   # over-long input is cut, then rejected as invalid
    nofile = c.post(f"{S}/{sid}/documents/pan", json=PAN).json()
    assert nofile["accepted"] is False and any(p["code"] == "MISSING_FILE" for p in nofile["problems"])
    assert c.officer.post(f"{S}/{sid}/documents/pan", files={"file": IMG}, fields=PAN).status_code == 403   # officers do not upload for customers
    other = client_for(ensure_user("bob", "customer"))
    assert other.get(f"{S}/{sid}/documents").status_code == 404 and up(other, sid, "pan", PAN).status_code == 404
    upload_all(c, sid)
    c.post(f"{S}/{sid}/documents/submit")
    c.post(f"{S}/{sid}/start")
    assert up(c, sid, "pan", PAN).status_code == 409                          # not once the live step has started


def test_same_id_used_by_another_customer_is_noted(make_client):
    c = make_client(require_documents=True)
    first = consented(c)
    upload_all(c, first)
    bob = client_for(ensure_user("bob", "customer"))
    second = consented(bob)
    upload_all(bob, second)
    bob.post(f"{S}/{second}/documents/submit")
    codes = {f["code"] for f in c.officer.get(f"{S}/{second}/documents").json()["findings"]}
    assert "ID_REUSED_BY_OTHER_CUSTOMER" in codes


def test_provenance_runs_on_uploaded_documents_and_is_never_a_missing_detector(make_client):
    from apps.documents.models import DocumentCheck  # noqa: F401
    from apps.provenance.detector import ProvenanceDetector
    from apps.signals.models import DetectorSignal
    c = make_client(lambda s: {"provenance": ProvenanceDetector(s)}, require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    sigs = DetectorSignal.objects.filter(session_id=sid, detector_name="provenance")
    assert sigs.count() == 2 and all(s.status == "ok" and s.details["doc_type"] in ("pan", "aadhaar") for s in sigs)
    c.post(f"{S}/{sid}/documents/submit")
    c.post(f"{S}/{sid}/start")
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert "provenance" not in rec["unavailable_detectors"] and "documents" not in rec["indicators"]


def test_documents_are_in_the_report_and_the_evidence_chain(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    c.post(f"{S}/{sid}/documents/submit")
    c.post(f"{S}/{sid}/start")
    c.post(f"{S}/{sid}/complete")
    rep = c.officer.get(f"{S}/{sid}/report").json()
    assert rep["documents"]["status"] == "accepted" and {d["doc_type"] for d in rep["documents"]["documents"]} == {"applicant", "pan", "aadhaar"}
    assert rep["integrity"]["matches_evidence_chain"] is True
    types = [e["event_type"] for e in c.officer.get(f"{S}/{sid}/evidence").json()["events"]]
    assert types.count("document.uploaded") == 3 and "documents.checked" in types
