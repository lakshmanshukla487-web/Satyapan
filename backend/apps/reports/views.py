from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsOfficer
from apps.core.audit import audit
from apps.core.errors import AppError
from apps.reports.serializers import ReportSerializer
from apps.reports.services import report_for
from apps.verification.services import get_or_404


@extend_schema(tags=["report"], responses=ReportSerializer)
@api_view(["GET"])
@permission_classes([IsOfficer])
def report(request, session_id):
    """Officer summary report. A completed session returns the report frozen at completion (with a check that it still
    matches the hash recorded in the evidence chain); anything else is generated now and marked as a live snapshot."""
    s = get_or_404(session_id)
    audit(request, "officer.read_report", session_id=s.id)
    return Response(report_for(s))


@extend_schema(tags=["report"], parameters=[OpenApiParameter("format", str, description="pdf (default), html or json")], responses={200: bytes})
@api_view(["GET"])
@permission_classes([IsOfficer])
def report_download(request, session_id):
    """Download the officer report as a file. It ends with a plain-language explanation of the colour and of every check."""
    s = get_or_404(session_id)
    fmt = (request.query_params.get("format") or "pdf").lower()
    if fmt not in ("pdf", "html", "json"):
        raise AppError("INVALID_FORMAT", "format must be pdf, html or json.", 400)
    data = report_for(s)
    audit(request, "officer.download_report", session_id=s.id, format=fmt)
    name = f"satyapan-report-{str(s.id)[:8]}.{fmt}"
    if fmt == "pdf":
        from apps.reports.pdf import render_pdf
        try:
            body, ctype = render_pdf(data), "application/pdf"
        except ImportError:
            raise AppError("PDF_UNAVAILABLE", "PDF support (reportlab) is not installed on the server. Download the HTML or JSON version instead.", 503)
    elif fmt == "html":
        from apps.reports.html import render_html
        body, ctype = render_html(data).encode("utf-8"), "text/html; charset=utf-8"
    else:
        import json
        body, ctype = json.dumps(data, indent=2, default=str).encode("utf-8"), "application/json"
    resp = HttpResponse(body, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
