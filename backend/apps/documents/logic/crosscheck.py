"""Cross-document verification: do the documents tell the same story about one person? (framework-free)

Each finding: {code, severity: indicator|note|ok, title, detail, docs}. Details never repeat the names or numbers
themselves (officers see those next to the finding); they only say what disagrees.
"""
from apps.documents.logic.validators import name_similarity, name_tokens

NAME_OK = 0.85       # at or above: consistent
NAME_PARTIAL = 0.60  # between: a note; below: an indicator
LABEL = {"applicant": "the application form", "pan": "the PAN", "aadhaar": "the Aadhaar", "passport": "the passport", "driving_licence": "the driving licence",
         "voter_id": "the voter ID", "address_proof": "the address proof", "cancelled_cheque": "the cancelled cheque"}


def _f(code, severity, title, detail, docs):
    return {"code": code, "severity": severity, "title": title, "detail": detail, "docs": docs}


def cross_check(docs: dict[str, dict]) -> list[dict]:
    """docs maps doc_type -> stored fields (plus optional file_sha256 and ocr). Returns the findings."""
    out: list[dict] = []
    app = docs.get("applicant")
    if not app:
        return out
    others = {k: v for k, v in docs.items() if k != "applicant"}

    # 1. names against the declared name
    consistent = []
    for k, v in others.items():
        if not v.get("name") or not app.get("name"):
            continue
        sim = name_similarity(app["name"], v["name"])
        if sim >= NAME_OK:
            consistent.append(k)
        elif sim >= NAME_PARTIAL:
            out.append(_f("NAME_PARTIAL_MATCH", "note", "Name only partly matches", f"The name on {LABEL[k]} is only a partial match to the declared name (similarity {sim:.2f}).", [k]))
        else:
            out.append(_f("NAME_MISMATCH", "indicator", "Name does not match", f"The name on {LABEL[k]} does not match the declared name (similarity {sim:.2f}).", [k]))
    if consistent:
        out.append(_f("NAME_CONSISTENT", "ok", "Names are consistent", f"The name matches the declared name on {len(consistent)} document(s): " + ", ".join(LABEL[k] for k in consistent) + ".", consistent))

    # 2. dates of birth
    dob_ok = []
    for k, v in others.items():
        if app.get("dob") and v.get("dob"):
            if v["dob"] == app["dob"]:
                dob_ok.append(k)
            else:
                out.append(_f("DOB_MISMATCH", "indicator", "Date of birth does not match", f"The date of birth on {LABEL[k]} differs from the declared date of birth.", [k]))
        elif app.get("dob") and v.get("year_of_birth"):
            if int(v["year_of_birth"]) == int(app["dob"][:4]):
                dob_ok.append(k)
            else:
                out.append(_f("YOB_MISMATCH", "indicator", "Year of birth does not match", f"The year of birth on {LABEL[k]} differs from the declared date of birth.", [k]))
    if dob_ok:
        out.append(_f("DOB_CONSISTENT", "ok", "Dates of birth are consistent", "The date of birth agrees on " + ", ".join(LABEL[k] for k in dob_ok) + ".", dob_ok))

    # 3. PAN structure: the 5th character is the first letter of the holder's surname
    pan = docs.get("pan")
    if pan and pan.get("pan_name_initial") and app.get("name"):
        toks = name_tokens(app["name"])
        if toks and pan["pan_name_initial"] not in {toks[0][0], toks[-1][0]}:
            out.append(_f("PAN_SURNAME_INITIAL_MISMATCH", "note", "PAN letter does not match the name",
                          "The 5th character of the PAN (the surname initial) matches neither end of the declared name.", ["pan", "applicant"]))

    # 4. PIN codes (a different PIN is normal: permanent vs current address)
    for k in ("aadhaar", "passport", "driving_licence", "voter_id", "address_proof"):
        v = others.get(k)
        if v and v.get("pin") and app.get("pin") and v["pin"] != app["pin"]:
            out.append(_f("PIN_DIFFERS", "note", "PIN code differs", f"The PIN code on {LABEL[k]} differs from the declared PIN code (a permanent and a current address can differ).", [k]))

    # 5. the same file uploaded as two different documents
    by_hash: dict[str, list[str]] = {}
    for k, v in others.items():
        if v.get("file_sha256"):
            by_hash.setdefault(v["file_sha256"], []).append(k)
    for ks in by_hash.values():
        if len(ks) > 1:
            out.append(_f("SAME_FILE_REUSED", "note", "One file used for several documents", "The same file was uploaded as " + " and ".join(LABEL[k] for k in ks) + ".", ks))

    # 6. optional OCR corroboration (only when Tesseract is installed)
    found = [k for k, v in others.items() if (v.get("ocr") or {}).get("number_found") is True]
    missing = [k for k, v in others.items() if (v.get("ocr") or {}).get("number_found") is False]
    if found:
        out.append(_f("OCR_NUMBER_CONFIRMED", "ok", "Typed number found in the image", "The typed ID number was read from the image of " + ", ".join(LABEL[k] for k in found) + ".", found))
    for k in missing:
        out.append(_f("OCR_NUMBER_NOT_FOUND", "note", "Typed number not found in the image", f"The typed ID number could not be read in the image of {LABEL[k]} (OCR can be unreliable on photos).", [k]))
    return out
