"""Uniform error body: {"error": {"code", "message", "request_id"}}."""
import logging

from django.db import DatabaseError, OperationalError, ProgrammingError
from django.http import Http404, JsonResponse
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import set_rollback

from apps.core.errors import AppError

log = logging.getLogger("satyapan")


def error_body(request, code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": getattr(request, "request_id", None)}}


def _first_validation_message(detail) -> str:
    """'username: Username must be ...' - the first problem, so the form can show something useful."""
    def walk(d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                yield from walk(v, k if not path else f"{path}.{k}")
        elif isinstance(d, (list, tuple)):
            for v in d:
                yield from walk(v, path)
        else:
            yield path, str(d)
    for field, text in walk(detail):
        return f"{field}: {text}" if field and field != "non_field_errors" else text
    return "The request was invalid."


def api_exception_handler(exc, context):
    request = context.get("request")
    raw = getattr(request, "_request", request)
    if isinstance(exc, AppError):
        status, code, msg = exc.status_code, exc.code, exc.message
    elif isinstance(exc, (drf.NotAuthenticated, drf.AuthenticationFailed)):
        status, code, msg = 401, "UNAUTHENTICATED", str(exc.detail) if isinstance(exc, drf.AuthenticationFailed) else "Authentication is required."
    elif isinstance(exc, drf.PermissionDenied):
        status, code, msg = 403, "FORBIDDEN", str(exc.detail)
    elif isinstance(exc, drf.ValidationError):
        status, code, msg = 422, "VALIDATION_ERROR", _first_validation_message(exc.detail)
    elif isinstance(exc, drf.ParseError):
        status, code, msg = 422, "VALIDATION_ERROR", "The request was invalid."
    elif isinstance(exc, drf.UnsupportedMediaType):
        status, code, msg = 415, "UNSUPPORTED_CONTENT_TYPE", "Unsupported request content type."
    elif isinstance(exc, (Http404, drf.NotFound)):
        status, code, msg = 404, "NOT_FOUND", "The requested resource was not found."
    elif isinstance(exc, drf.MethodNotAllowed):
        status, code, msg = 405, "METHOD_NOT_ALLOWED", "Method not allowed."
    elif isinstance(exc, drf.NotAcceptable):
        status, code, msg = 406, "NOT_ACCEPTABLE", "Not acceptable."
    elif isinstance(exc, drf.APIException):
        status, code, msg = exc.status_code, "REQUEST_ERROR", "The request could not be processed."
    elif isinstance(exc, (OperationalError, ProgrammingError)):
        # Almost always: the database tables are missing or out of date (migrations not applied, or an old satyapan.db
        # from a previous version). Say so in the server log; tell the client something actionable but harmless.
        log.error("DATABASE NOT READY (%s): %s  -> run `python manage.py setup_db` in the backend folder. request_id=%s",
                  type(exc).__name__, exc, getattr(raw, "request_id", None), exc_info=exc)
        status, code, msg = 503, "DATABASE_NOT_READY", "The server database is not set up yet. Ask the administrator to run the database setup."
    elif isinstance(exc, DatabaseError):
        log.error("database error %s request_id=%s", type(exc).__name__, getattr(raw, "request_id", None), exc_info=exc)
        status, code, msg = 503, "DATABASE_ERROR", "The database is temporarily unavailable. Please try again."
    else:
        # Full traceback goes to the SERVER log only (never to the client), with the request id the client also sees.
        log.error("unhandled %s on %s %s request_id=%s", type(exc).__name__, getattr(raw, "method", "?"), getattr(raw, "path", "?"),
                  getattr(raw, "request_id", None), exc_info=exc)
        status, code, msg = 500, "INTERNAL_ERROR", "An unexpected error occurred."
    set_rollback()
    headers = {"WWW-Authenticate": exc.auth_header} if getattr(exc, "auth_header", None) else None
    return Response(error_body(raw, code, msg), status=status, headers=headers)


def json_404(request, exception=None):
    return JsonResponse(error_body(request, "NOT_FOUND", "The requested resource was not found."), status=404)


def json_500(request):
    log.error("unhandled error rendered by the Django 500 handler path=%s", getattr(request, "path", "?"), exc_info=True)
    return JsonResponse(error_body(request, "INTERNAL_ERROR", "An unexpected error occurred."), status=500)
