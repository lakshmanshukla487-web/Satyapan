"""Framework-free unit tests: documents, pulse, integrity and provenance logic. No database needed."""
import io
from datetime import date

import numpy as np
import pytest

from apps.documents.logic import crosscheck as cc
from apps.documents.logic import validators as v
from apps.integrity.logic import evaluate_probe
from apps.provenance.logic import analyze_bytes
from apps.pulse.logic import analyze_rgb

TODAY = date(2026, 10, 22)


def aadhaar(body="23456789012"):
    return body + v.verhoeff_check_digit(body)


def test_verhoeff_reference_values():
    assert v.verhoeff_check_digit("236") == "3" and v.verhoeff_valid("2363")
    assert v.verhoeff_check_digit("12345") == "1" and v.verhoeff_valid("123451")
    assert not v.verhoeff_valid("2364")


def test_aadhaar_checks_and_masking():
    a = aadhaar()
    fields, number, problems = v.check_document("aadhaar", {"name": "Rahul Kumar Sharma", "aadhaar_number": f"{a[:4]} {a[4:8]} {a[8:]}", "dob": "15/08/1995"}, TODAY)
    assert not problems and number == a and fields["number_masked"] == "XXXX XXXX " + a[-4:] and fields["year_of_birth"] == 1995
    assert "aadhaar_number" not in fields and a not in str(fields)  # the full number is never part of what gets stored
    bad = a[:-1] + ("0" if a[-1] != "0" else "1")
    assert v.check_document("aadhaar", {"name": "Rahul", "aadhaar_number": bad, "dob": "15/08/1995"}, TODAY)[2][0]["code"] == "INVALID_AADHAAR"
    assert v.check_document("aadhaar", {"name": "Rahul", "aadhaar_number": "123456789012", "dob": "15/08/1995"}, TODAY)[2][0]["code"] == "INVALID_AADHAAR"


def test_pan_rules():
    f, n, p = v.check_document("pan", {"name": "Rahul Sharma", "pan_number": "abcps1234f", "dob": "1995-08-15"}, TODAY)
    assert not p and f["pan_name_initial"] == "S" and f["number_masked"] == "ABC*****4F" and n == "ABCPS1234F"
    assert v.check_document("pan", {"name": "R S", "pan_number": "ABCCS1234F", "dob": "1995-08-15"}, TODAY)[2][0]["code"] == "PAN_NOT_INDIVIDUAL"
    assert v.check_document("pan", {"name": "R S", "pan_number": "ABCDE12345", "dob": "1995-08-15"}, TODAY)[2][0]["code"] == "INVALID_PAN"


def test_applicant_rules():
    assert any(x["code"] == "UNDER_AGE" for x in v.check_document("applicant", {"full_name": "Rahul Sharma", "dob": "2012-01-01", "mobile": "9876543210", "pin": "141001"}, TODAY)[2])
    codes = {x["code"] for x in v.check_document("applicant", {"full_name": "Rahul Sharma", "dob": "01/01/1990", "mobile": "5876543210", "pin": "041001", "email": "bad"}, TODAY)[2]}
    assert codes == {"INVALID_MOBILE", "INVALID_PIN", "INVALID_EMAIL"}
    assert [x["field"] for x in v.check_document("applicant", {}, TODAY)[2]] == ["full_name", "dob", "mobile", "pin"]


def test_other_documents():
    base = {"name": "Rahul Sharma", "dob": "1990-01-01"}
    assert any(x["code"] == "DOCUMENT_EXPIRED" for x in v.check_document("passport", {**base, "passport_number": "K1234567", "expiry_date": "2020-01-01"}, TODAY)[2])
    assert not v.check_document("passport", {**base, "passport_number": "K1234567", "expiry_date": "2031-01-01"}, TODAY)[2]
    assert not v.check_document("driving_licence", {**base, "dl_number": "PB10 20110012345", "expiry_date": "2040-01-01"}, TODAY)[2]
    assert v.check_document("driving_licence", {**base, "dl_number": "XYZ", "expiry_date": "2040-01-01"}, TODAY)[2][0]["severity"] == "warning"
    assert not v.check_document("voter_id", {"name": "Rahul Sharma", "epic_number": "ABC1234567"}, TODAY)[2]
    assert not v.check_document("address_proof", {"name": "Rahul Sharma", "pin": "141001", "doc_date": "2026-09-30", "kind": "electricity"}, TODAY)[2]
    assert v.check_document("address_proof", {"name": "Rahul Sharma", "pin": "141001", "doc_date": "2026-03-01", "kind": "electricity"}, TODAY)[2][0]["code"] == "ADDRESS_PROOF_STALE"
    f, _, p = v.check_document("cancelled_cheque", {"name": "Rahul Sharma", "ifsc": "hdfc0001234", "account_last4": "6789"}, TODAY)
    assert not p and f["ifsc"] == "HDFC0001234"
    assert {x["code"] for x in v.check_document("cancelled_cheque", {"name": "Rahul Sharma", "ifsc": "HDFC1001234", "account_last4": "67"}, TODAY)[2]} == {"INVALID_IFSC", "INVALID_ACCOUNT_DIGITS"}


@pytest.mark.parametrize("a,b,lo,hi", [("Rahul Sharma", "RAHUL KUMAR SHARMA", 0.85, 1.01), ("Lakshman Singh", "Laxman Singh", 0.85, 1.01), ("R K Sharma", "Rahul Kumar Sharma", 0.85, 1.01),
                                       ("Mr. Rahul Sharma", "Sharma Rahul", 0.95, 1.01), ("Rahul Sharma", "Priya Verma", 0.0, 0.6), ("Rahul Sharma", "Rohit Sharma", 0.6, 0.85)])
def test_name_similarity(a, b, lo, hi):
    assert lo <= v.name_similarity(a, b) < hi


def test_cross_check_consistent_and_inconsistent():
    good = {"applicant": {"name": "Rahul Sharma", "dob": "1995-08-15", "pin": "141001"}, "pan": {"name": "RAHUL SHARMA", "dob": "1995-08-15", "pan_name_initial": "S"},
            "aadhaar": {"name": "Rahul Sharma", "year_of_birth": 1995, "pin": "141001", "ocr": {"number_found": True}}}
    assert {x["code"] for x in cc.cross_check(good)} == {"NAME_CONSISTENT", "DOB_CONSISTENT", "OCR_NUMBER_CONFIRMED"}
    bad = {"applicant": {"name": "Rahul Sharma", "dob": "1995-08-15", "pin": "141001"}, "pan": {"name": "Priya Verma", "dob": "1990-01-01", "pan_name_initial": "V", "file_sha256": "x"},
           "aadhaar": {"name": "Rahul Sharma", "year_of_birth": 1999, "pin": "110001", "file_sha256": "x"}}
    sev = {x["code"]: x["severity"] for x in cc.cross_check(bad)}
    assert sev["NAME_MISMATCH"] == sev["DOB_MISMATCH"] == sev["YOB_MISMATCH"] == "indicator"
    assert sev["PIN_DIFFERS"] == sev["SAME_FILE_REUSED"] == sev["PAN_SURNAME_INITIAL_MISMATCH"] == "note"
    assert all("Priya" not in x["detail"] and "Verma" not in x["detail"] for x in cc.cross_check(bad))  # findings never repeat the names


def _trace(amp, seconds=14, fps=30.0, hz=1.2, noise=0.15, seed=1):
    rng, t = np.random.default_rng(seed), np.arange(int(fps * seconds)) / fps
    x = np.array([180.0, 140.0, 120.0])[None, :] * np.ones((len(t), 3))
    wave = amp * np.sin(2 * np.pi * hz * t)
    x[:, 0] += 0.3 * wave
    x[:, 1] += wave
    x[:, 2] += 0.5 * wave
    return x + rng.normal(0, noise, x.shape)


def test_pulse_found_absent_and_quality_gates():
    r = analyze_rgb(_trace(0.6), 30.0)
    assert r["quality"] == "good" and r["pulse_present"] and abs(r["bpm"] - 72) < 4
    r = analyze_rgb(_trace(0.0, noise=0.4), 30.0)
    assert r["quality"] == "good" and not r["pulse_present"]
    assert analyze_rgb(_trace(0.6)[:150], 30.0)["quality"] == "poor"      # shorter than 10 s
    assert analyze_rgb(_trace(0.6) * 0.1, 30.0)["quality"] == "poor"      # too dark


def test_integrity_rules():
    rng = np.random.default_rng(1)
    jitter = list(33.3 + rng.normal(0, 2.5, 120))
    assert evaluate_probe({"camera_label": "Integrated Webcam", "frame_rate": 30, "intervals_ms": jitter})["score"] == 0.0
    soft = evaluate_probe({"camera_label": "OBS Virtual Camera", "frame_rate": 30, "intervals_ms": jitter})
    assert not soft["hard"] and soft["notes"] and soft["score"] == 0.0          # a virtual-camera NAME alone is only a note
    hard = evaluate_probe({"camera_label": "OBS Virtual Camera", "frame_rate": 30, "intervals_ms": [33.333] * 120})
    assert hard["hard"] and hard["score"] == 1.0                                # name + unnaturally regular timing
    assert evaluate_probe({"camera_label": "", "intervals_ms": []})["error_code"] == "NO_PROBE_DATA"
    assert evaluate_probe({"camera_label": "Virtual Camera", "frame_rate": 30, "intervals_ms": list(66.6 + rng.normal(0, 5, 120))})["hard"]  # fps mismatch


def test_provenance_notes_never_accuse():
    from PIL import Image, PngImagePlugin
    buf = io.BytesIO()
    im = Image.new("RGB", (400, 400), (200, 200, 200))
    ex = im.getexif()
    ex[305] = "Adobe Photoshop 25.0"
    im.save(buf, "JPEG", exif=ex)
    a = analyze_bytes(buf.getvalue())
    assert a["editor_software"] == "Photoshop" and a["kind"] == "jpeg" and not a["too_small"]
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a cat, Steps: 20, Model: Stable Diffusion")
    buf = io.BytesIO()
    Image.new("RGB", (400, 400)).save(buf, "PNG", pnginfo=info)
    assert analyze_bytes(buf.getvalue())["generator_metadata"]
    buf = io.BytesIO()
    Image.new("RGB", (400, 400)).save(buf, "PNG")
    clean = analyze_bytes(buf.getvalue())
    assert not clean["generator_metadata"] and clean["editor_software"] is None and not clean["c2pa_manifest_marker"]
    assert analyze_bytes(b"%PDF-1.4\n/Producer (Microsoft Word)\n/Creator (Canva)\n")["editor_software"] == "Canva"
