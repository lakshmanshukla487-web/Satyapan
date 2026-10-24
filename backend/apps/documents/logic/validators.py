"""Format, checksum and plausibility checks for Indian bank-account KYC documents (framework-free, unit-testable).

What this is: structural validation of what the customer typed (PAN format and holder type, Aadhaar Verhoeff checksum,
passport / licence / voter-ID / IFSC formats, dates, age, expiry, freshness of address proof).
What this is NOT: a lookup in UIDAI, NSDL, DigiLocker or any registry. A well-formed number can still be fake; the
production path is the official verification APIs (see docs/ARCHITECTURE.md).
"""
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

OVD_TYPES = ("aadhaar", "passport", "driving_licence", "voter_id")  # officially valid documents for identity (+ address)
FIELDS = {
    "applicant": {"required": ["full_name", "dob", "mobile", "pin"], "optional": ["email"]},
    "pan": {"required": ["name", "pan_number", "dob"], "optional": []},
    "aadhaar": {"required": ["name", "aadhaar_number"], "optional": ["dob", "year_of_birth", "pin"]},
    "passport": {"required": ["name", "passport_number", "dob", "expiry_date"], "optional": ["pin"]},
    "driving_licence": {"required": ["name", "dl_number", "dob", "expiry_date"], "optional": ["pin"]},
    "voter_id": {"required": ["name", "epic_number"], "optional": ["dob", "pin"]},
    "address_proof": {"required": ["name", "pin", "doc_date", "kind"], "optional": []},
    "cancelled_cheque": {"required": ["name", "ifsc", "account_last4"], "optional": []},
}
FILE_REQUIRED = frozenset(FIELDS) - {"applicant"}
NUMBER_FIELD = {"pan": "pan_number", "aadhaar": "aadhaar_number", "passport": "passport_number", "driving_licence": "dl_number", "voter_id": "epic_number"}
LABELS = {"full_name": "Full name", "name": "Name as on the document", "dob": "Date of birth", "mobile": "Mobile number", "pin": "PIN code", "email": "Email",
          "pan_number": "PAN", "aadhaar_number": "Aadhaar number", "passport_number": "Passport number", "dl_number": "Driving licence number",
          "epic_number": "Voter ID (EPIC) number", "expiry_date": "Expiry date", "doc_date": "Document date", "kind": "Document kind", "ifsc": "IFSC",
          "account_last4": "Last 4 digits of the account number", "year_of_birth": "Year of birth"}
ALL_FIELD_NAMES = frozenset(f for spec in FIELDS.values() for f in spec["required"] + spec["optional"])

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
PAN_HOLDER_TYPES = "ABCFGHLJPT"  # 4th character: A AOP, B BOI, C company, F firm, G govt, H HUF, L local authority, J juridical person, P individual, T trust
AADHAAR_RE = re.compile(r"^[2-9][0-9]{11}$")
PASSPORT_RE = re.compile(r"^[A-PR-WY][1-9][0-9]{5}[1-9]$")
DL_RE = re.compile(r"^[A-Z]{2}[0-9]{2}(19|20)[0-9]{2}[0-9]{7}$")
EPIC_RE = re.compile(r"^[A-Z]{3}[0-9]{7}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")
PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s]{2,}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,98}$")
UTILITY_KINDS = ("electricity", "gas", "water", "telephone", "bank_statement")
UTILITY_MAX_AGE_DAYS = {"bank_statement": 92}  # others: 62 days (RBI: utility bill not more than two months old)

# --- Verhoeff checksum (the check digit of the 12-digit Aadhaar number) ---
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(number: str) -> str:
    """Check digit to append to `number` (used by tests to build valid sample numbers)."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def parse_date(raw) -> date | None:
    s = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _norm_id(v) -> str:
    return re.sub(r"[\s\-]", "", str(v or "")).upper()


def clean_name(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def age_on(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# --- names ---
_TITLES = {"MR", "MRS", "MS", "MISS", "DR", "SHRI", "SMT", "SRI", "SHREE", "KUMARI", "KU", "LATE", "PROF"}


def name_tokens(name: str) -> list[str]:
    return [t for t in re.sub(r"[^A-Z ]", " ", str(name or "").upper()).split() if t and t not in _TITLES]


def name_similarity(a: str, b: str) -> float:
    """0..1. Tolerant of middle names, initials, order and common transliteration differences (Lakshman / Laxman)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    if len(ta) > len(tb):
        ta, tb = tb, ta  # the shorter name must be explained by the longer one ("Rahul Sharma" vs "Rahul Kumar Sharma")

    def match(t: str, u: str) -> float:
        if len(t) == 1 or len(u) == 1:
            return 0.9 if t[0] == u[0] else 0.0
        return SequenceMatcher(None, t, u).ratio()
    return round(sum(max(match(t, u) for u in tb) for t in ta) / len(ta), 3)


def mask_number(doc_type: str, n: str) -> str:
    if doc_type == "aadhaar":
        return "XXXX XXXX " + n[-4:]
    if doc_type == "pan":
        return n[:3] + "*****" + n[-2:]
    if len(n) <= 5:
        return "*" * len(n)
    return n[:2] + "*" * (len(n) - 4) + n[-2:]


def check_document(doc_type: str, data: dict, today: date | None = None) -> tuple[dict, str | None, list[dict]]:
    """Validate the typed fields of one document.

    Returns (fields, number, problems):
      fields   sanitised values that are safe to store (never the full ID number; only a masked form and derived flags)
      number   the normalised ID number, used for hashing and OCR comparison only; the caller must not store it
      problems [{code, field, severity: error|warning, message}]; messages are written for the customer.
    """
    today = today or date.today()
    spec = FIELDS[doc_type]
    problems: list[dict] = []
    fields: dict = {}
    number: str | None = None

    def add(code: str, field: str, message: str, severity: str = "error") -> None:
        problems.append({"code": code, "field": field, "severity": severity, "message": message})

    def get(f: str) -> str:
        return str(data.get(f, "") or "").strip()

    for f in spec["required"]:
        if not get(f):
            add("MISSING_FIELD", f, f"{LABELS.get(f, f)} is required.")

    name_key = "full_name" if doc_type == "applicant" else "name"
    if get(name_key):
        nm = clean_name(get(name_key))
        if NAME_RE.match(nm):
            fields["name"] = nm
        else:
            add("INVALID_NAME", name_key, "Enter the name using letters, spaces, dots, apostrophes or hyphens only.")

    dob = None
    if get("dob"):
        dob = parse_date(get("dob"))
        if dob is None or dob > today or age_on(dob, today) > 110:
            add("INVALID_DOB", "dob", "Enter a valid date of birth (DD/MM/YYYY).")
            dob = None
        else:
            fields["dob"] = dob.isoformat()
            if doc_type == "applicant" and age_on(dob, today) < 18:
                add("UNDER_AGE", "dob", "Account holders must be 18 or older. Minor accounts are opened with a guardian, not through this flow.")

    if get("pin"):
        if PIN_RE.match(get("pin")):
            fields["pin"] = get("pin")
        else:
            add("INVALID_PIN", "pin", "Enter a valid 6-digit PIN code.")

    if doc_type == "applicant":
        if get("mobile") and not MOBILE_RE.match(get("mobile")):
            add("INVALID_MOBILE", "mobile", "Enter a valid 10-digit Indian mobile number (starting 6-9).")
        elif get("mobile"):
            fields["mobile_masked"] = "*" * 6 + get("mobile")[-4:]
        if get("email"):
            if EMAIL_RE.match(get("email")) and len(get("email")) <= 100:
                fields["email_masked"] = get("email")[0] + "***@" + get("email").split("@")[1]
            else:
                add("INVALID_EMAIL", "email", "Enter a valid email address.")

    elif doc_type == "pan":
        number = _norm_id(get("pan_number"))
        if number and not PAN_RE.match(number):
            add("INVALID_PAN", "pan_number", "A PAN has 5 letters, 4 digits and 1 letter (for example ABCPE1234F).")
            number = None
        elif number:
            if number[3] not in PAN_HOLDER_TYPES:
                add("INVALID_PAN", "pan_number", "The 4th character of this PAN is not a valid holder type.")
            elif number[3] != "P":
                add("PAN_NOT_INDIVIDUAL", "pan_number", "This PAN belongs to an organisation. Use the individual's PAN to open a personal account.")
            fields.update({"pan_holder_type": number[3], "pan_name_initial": number[4], "number_masked": mask_number("pan", number)})

    elif doc_type == "aadhaar":
        number = _norm_id(get("aadhaar_number"))
        if number and not AADHAAR_RE.match(number):
            add("INVALID_AADHAAR", "aadhaar_number", "Enter the 12-digit Aadhaar number (not the 16-digit Virtual ID).")
            number = None
        elif number and not verhoeff_valid(number):
            add("INVALID_AADHAAR", "aadhaar_number", "This Aadhaar number fails its checksum. Check for a typing mistake.")
            number = None
        elif number:
            fields["number_masked"] = mask_number("aadhaar", number)
        yob = get("year_of_birth")
        if yob:
            if yob.isdigit() and 1900 <= int(yob) <= today.year:
                fields["year_of_birth"] = int(yob)
            else:
                add("INVALID_YOB", "year_of_birth", "Enter a valid 4-digit year of birth.")
        elif dob:
            fields["year_of_birth"] = dob.year
        if not get("dob") and not yob:
            add("MISSING_FIELD", "dob", "Enter the date of birth or the year of birth printed on the Aadhaar.")

    elif doc_type in ("passport", "driving_licence", "voter_id"):
        key = NUMBER_FIELD[doc_type]
        number = _norm_id(get(key))
        regex, label, sev = {"passport": (PASSPORT_RE, "passport", "error"), "driving_licence": (DL_RE, "driving licence", "warning"), "voter_id": (EPIC_RE, "voter ID", "warning")}[doc_type]
        if number and not regex.match(number):
            add("INVALID_ID_FORMAT", key, f"This does not look like a standard Indian {label} number.", sev)
            if sev == "error":
                number = None
        if number:
            fields["number_masked"] = mask_number(doc_type, number)
        if doc_type in ("passport", "driving_licence") and get("expiry_date"):
            exp = parse_date(get("expiry_date"))
            if exp is None:
                add("INVALID_EXPIRY", "expiry_date", "Enter a valid expiry date (DD/MM/YYYY).")
            elif exp < today:
                add("DOCUMENT_EXPIRED", "expiry_date", f"This {label} has expired and cannot be used as an identity document.")
            else:
                fields["expiry_date"] = exp.isoformat()

    elif doc_type == "address_proof":
        kind, d = get("kind").lower(), parse_date(get("doc_date"))
        if kind and kind not in UTILITY_KINDS:
            add("INVALID_KIND", "kind", f"Choose one of: {', '.join(UTILITY_KINDS)}.")
        elif kind:
            fields["kind"] = kind
        if get("doc_date"):
            limit = UTILITY_MAX_AGE_DAYS.get(kind, 62)
            if d is None or d > today:
                add("INVALID_DATE", "doc_date", "Enter the date printed on the document (DD/MM/YYYY).")
            elif (today - d) > timedelta(days=limit):
                add("ADDRESS_PROOF_STALE", "doc_date", f"Address proof must be recent (not older than about {limit // 30} months).")
            else:
                fields["doc_date"] = d.isoformat()

    elif doc_type == "cancelled_cheque":
        ifsc = _norm_id(get("ifsc"))
        if ifsc and not IFSC_RE.match(ifsc):
            add("INVALID_IFSC", "ifsc", "An IFSC has 4 letters, a zero, then 6 letters or digits (for example HDFC0001234).")
        elif ifsc:
            fields["ifsc"] = ifsc
        if get("account_last4") and not re.fullmatch(r"[0-9]{4}", get("account_last4")):
            add("INVALID_ACCOUNT_DIGITS", "account_last4", "Enter only the last 4 digits of the account number.")
        elif get("account_last4"):
            fields["account_last4"] = get("account_last4")
    return fields, number, problems
