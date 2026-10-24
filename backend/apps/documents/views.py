from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.core.audit import audit
from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.core.validation import read_limited
from apps.documents import services
from apps.documents.logic.validators import FIELDS
from apps.verification.services import get_owned, get_visible, require_consent

NEUTRAL_OK = "Thank you. Your documents have been received."
UPLOAD_SCHEMA = {"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}}


def _editable(s) -> None:
    require_consent(s)
    if s.status != "ready":
        raise AppError("INVALID_STATE_TRANSITION", "Documents can only be changed after consent and before the live check starts.", 409)


@extend_schema(tags=["documents"], request=UPLOAD_SCHEMA, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsCustomer])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def upload(request, session_id, doc_type):
    """Upload (or replace) one document: typed fields + the image/PDF (not needed for the application form)."""
    if doc_type not in FIELDS:
        raise AppError("UNKNOWN_DOCUMENT_TYPE", "Unknown document type.", 404)
    s = get_owned(session_id, request.user)
    _editable(s)
    f = request.FILES.get("file")
    file_bytes = read_limited(f, get_runtime().settings.max_document_mb) if f is not None else None
    _, problems = services.process_upload(s, doc_type, services.clean_input(request.data), file_bytes)
    return Response({"doc_type": doc_type, "accepted": not any(p["severity"] == "error" for p in problems), "problems": problems})


@extend_schema(tags=["documents"], request=None, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsCustomer])
def submit(request, session_id):
    """Run the cross-document verification. The customer only learns whether something needs fixing."""
    s = get_owned(session_id, request.user)
    _editable(s)
    check, blocking, missing = services.submit_documents(s)
    status = services.CUSTOMER_STATUS[check.status]
    return Response({"status": status, "problems": blocking, "missing": missing, "message": NEUTRAL_OK if status == "accepted" else "Please fix the items below and submit again."})


@extend_schema(tags=["documents"], responses={200: dict})
@api_view(["GET"])
def documents(request, session_id):
    """Customer: the status of their own uploads (what they can fix). Officer: everything, including cross-document findings."""
    s = get_visible(session_id, request.user)
    if request.user.is_officer:
        audit(request, "officer.read_documents", session_id=s.id)
        return Response(services.officer_view(s))
    return Response(services.customer_view(s))
