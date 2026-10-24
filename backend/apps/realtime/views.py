from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.runtime import get_runtime


@extend_schema(tags=["realtime"], responses=dict)
@api_view(["GET"])
def rtc_config(request):
    """ICE servers for the officer-customer live call. STUN is contacted by the browser itself; TURN (optional) relays the
    media when two browsers cannot reach each other directly. Any signed-in user may read it."""
    cfg = get_runtime().settings
    servers = []
    stun = [u.strip() for u in cfg.stun_urls.split(",") if u.strip()]
    if stun:
        servers.append({"urls": stun})
    turn = [u.strip() for u in cfg.turn_urls.split(",") if u.strip()]
    if turn and cfg.turn_username and cfg.turn_credential:
        servers.append({"urls": turn, "username": cfg.turn_username, "credential": cfg.turn_credential})
    return Response({"enabled": bool(cfg.enable_live_call), "iceServers": servers, "relayConfigured": bool(turn)})
