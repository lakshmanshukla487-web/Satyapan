import uuid

from django.db import models
from django.utils import timezone


class KycDocument(models.Model):
    """One KYC document of a session. Only sanitised data is stored: never the image or PDF itself (it is processed in
    memory), never a full Aadhaar/PAN/passport number (only a masked form and a keyed hash for duplicate detection)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey("verification.VerificationSession", on_delete=models.CASCADE, related_name="kyc_documents")
    doc_type = models.CharField(max_length=20)  # applicant | pan | aadhaar | passport | driving_licence | voter_id | address_proof | cancelled_cheque
    info = models.JSONField(default=dict)       # sanitised, storable fields (name, dob, pin, number_masked, derived flags)
    problems = models.JSONField(default=list)   # [{code, field, severity, message}]
    id_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)  # HMAC of the normalised ID number
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    file_kind = models.CharField(max_length=10, blank=True, default="none")  # jpeg | png | pdf | none
    ocr = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "doc_type"], name="uniq_kyc_session_doctype")]


class DocumentCheck(models.Model):
    """Result of submitting the documents: needs_correction (fixable errors or missing documents), flagged (cross-document
    disagreement: the officer reviews it, the customer may continue) or accepted."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField("verification.VerificationSession", on_delete=models.CASCADE, related_name="document_check")
    status = models.CharField(max_length=20)
    summary = models.JSONField(default=dict)  # {findings: [...], missing: [...], blocking: [...]}
    checked_at = models.DateTimeField(default=timezone.now)
