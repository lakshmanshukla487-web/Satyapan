from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import IsOfficer
from apps.core.runtime import get_runtime


@extend_schema(tags=["health"], responses={200: dict})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@extend_schema(tags=["health"], responses={200: dict})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ready(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return Response({"ready": db_ok, "database": "ok" if db_ok else "unavailable"})  # detector state is officer-only (models/status)


@extend_schema(tags=["health"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsOfficer])
def models_status(request):
    return Response({"detectors": get_runtime().registry.status()})
