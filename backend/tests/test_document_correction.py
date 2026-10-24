"""Removing and replacing submitted documents: ownership, lifecycle rules, stale results never reused, other documents untouched."""
from apps.biometrics.models import Observation
from apps.documents.models import DocumentCheck, KycDocument
from apps.provenance.detector import ProvenanceDetector
from apps.signals.models import DetectorSignal
from tests.conftest import client_for, ensure_user, png_bytes
from tests.test_documents import AADH, APPLICANT, IMG, PAN, S, consented, up, upload_all

PASSPORT = {"name": "Rahul Sharma", "passport_number": "K1234567", "dob": "15/08/1995", "expiry_date": "01/01/2033"}


def remove(c, sid, t):
    return c.post(f"{S}/{sid}/documents/{t}/remove")


def test_remove_resets_only_that_document_and_the_check(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "accepted"
    r = remove(c, sid, "aadhaar")
    assert r.status_code == 200 and r.json() == {"doc_type": "aadhaar", "removed": True, "status": "not_submitted"}
    assert set(KycDocument.objects.filter(session_id=sid).values_list("doc_type", flat=True)) == {"applicant", "pan"}  # the others stay
    assert not DocumentCheck.objects.filter(session_id=sid).exists()          # the old "accepted" can no longer open the live step
    assert c.post(f"{S}/{sid}/start").status_code == 409
    view = c.get(f"{S}/{sid}/documents").json()
    assert view["status"] == "not_submitted" and {d["doc_type"] for d in view["documents"]} == {"applicant", "pan"}
    sub = c.post(f"{S}/{sid}/documents/submit").json()
    assert sub["status"] == "needs_correction" and sub["missing"] == ["identity_document"]
    assert up(c, sid, "aadhaar", AADH).json()["accepted"]                     # correct it without starting over
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "accepted"
    assert c.post(f"{S}/{sid}/start").status_code == 200
    types = [e["event_type"] for e in c.officer.get(f"{S}/{sid}/evidence").json()["events"]]
    assert "document.removed" in types                                         # auditable, without the file


def test_wrong_document_type_can_be_taken_back(make_client):
    """The customer first sent a passport with a typo (blocking), then switched to Aadhaar: removing the passport unblocks them."""
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    bad = up(c, sid, "passport", {**PASSPORT, "passport_number": "123"}).json()
    assert bad["accepted"] is False
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "needs_correction"   # the stale passport blocks
    assert remove(c, sid, "passport").json()["removed"] is True
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "accepted"


def test_optional_document_with_an_error_can_be_removed(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    r = up(c, sid, "cancelled_cheque", {"name": "Rahul Sharma", "ifsc": "BAD", "account_last4": "12"}).json()
    assert r["accepted"] is False
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "needs_correction"
    remove(c, sid, "cancelled_cheque")
    assert c.post(f"{S}/{sid}/documents/submit").json()["status"] == "accepted"


def test_remove_rules(make_client):
    c = make_client(require_documents=True)
    sid = c.post(S).json()["id"]
    assert remove(c, sid, "pan").status_code == 403                            # consent first (same rule as uploads)
    c.post(f"{S}/{sid}/consent", json={"granted": True})
    assert remove(c, sid, "not_a_doc").status_code == 404
    assert remove(c, sid, "pan").json() == {"doc_type": "pan", "removed": False, "status": "not_submitted"}  # idempotent
    upload_all(c, sid)
    other = client_for(ensure_user("bob", "customer"))
    assert remove(other, sid, "pan").status_code == 404                        # not the owner: looks like it does not exist
    assert remove(c.officer, sid, "pan").status_code == 403                    # officers do not change customer documents
    assert KycDocument.objects.filter(session_id=sid, doc_type="pan").exists()
    c.post(f"{S}/{sid}/documents/submit")
    c.post(f"{S}/{sid}/start")
    r = remove(c, sid, "pan")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"   # immutable once the live check runs
    assert KycDocument.objects.filter(session_id=sid, doc_type="pan").exists()


def test_replaced_or_removed_file_results_are_never_reused(make_client):
    c = make_client(lambda s: {"provenance": ProvenanceDetector(s)}, require_documents=True)
    sid = consented(c)
    upload_all(c, sid)
    # a face embedding taken from the first Aadhaar photo (as the face model would store it)
    Observation.objects.create(session_id=sid, kind="doc_face", data={"doc_type": "aadhaar", "embedding": [0.1] * 4})
    first = KycDocument.objects.get(session_id=sid, doc_type="aadhaar").file_sha256
    new_img = ("new.png", png_bytes((400, 400), (10, 200, 30)), "image/png")
    r = c.post(f"{S}/{sid}/documents/aadhaar", files={"file": new_img}, fields=AADH)
    assert r.status_code == 200 and r.json()["accepted"]
    doc = KycDocument.objects.get(session_id=sid, doc_type="aadhaar")
    assert doc.file_sha256 != first                                            # only the latest file's information is kept
    assert not Observation.objects.filter(session_id=sid, kind="doc_face", data__doc_type="aadhaar").exists()
    prov = list(DetectorSignal.objects.filter(session_id=sid, detector_name="provenance", details__doc_type="aadhaar").order_by("created_at"))
    assert len(prov) == 2 and prov[0].details.get("superseded") is True and not prov[1].details.get("superseded")
    assert prov[1].details["file_sha256"] == doc.file_sha256
    ev = [e for e in c.officer.get(f"{S}/{sid}/evidence").json()["events"] if e["event_type"] == "document.uploaded" and e["payload"]["doc_type"] == "aadhaar"]
    assert ev[-1]["payload"]["replaced"] is True and ev[-1]["payload"]["previous_file_sha256"] == first
    remove(c, sid, "aadhaar")
    assert all(s.details.get("superseded") for s in DetectorSignal.objects.filter(session_id=sid, detector_name="provenance", details__doc_type="aadhaar"))
    # the decision engine and the officer's signal cards ignore superseded results
    from apps.decision_engine.services import aggregate_signals, latest_signals
    assert all(not (s.details or {}).get("superseded") for s in latest_signals(sid))
    prov_agg = next(a for a in aggregate_signals(sid) if a["detector_name"] == "provenance")
    assert prov_agg["n_samples"] == 1                                          # only the PAN file's result remains


def test_customer_view_shows_what_was_received_without_file_names(make_client):
    c = make_client(require_documents=True)
    sid = consented(c)
    up(c, sid, "applicant", APPLICANT, file=False)
    up(c, sid, "pan", PAN)
    docs = {d["doc_type"]: d for d in c.get(f"{S}/{sid}/documents").json()["documents"]}
    assert docs["pan"]["has_file"] is True and docs["pan"]["file_kind"] == "png" and docs["applicant"]["has_file"] is False
    assert "doc.png" not in str(docs) and IMG[0] not in str(docs)


def test_officer_feed_hears_about_removals(make_client):
    from apps.realtime.events import EVENTS, FEED_EVENTS
    assert "document.removed" in EVENTS and "document.removed" in FEED_EVENTS
