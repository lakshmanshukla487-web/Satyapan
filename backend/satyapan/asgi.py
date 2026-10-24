import os
import sys

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyapan.settings")
django_asgi_app = get_asgi_application()  # must run before importing anything that touches models

from apps.core.asgi_middleware import BodyLimitMiddleware  # noqa: E402
from apps.core.runtime import warm_up  # noqa: E402
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

# Load every model ONCE, on the CPU, while the server process starts (before it accepts its first request). From here on
# only inference runs. Skipped under pytest, which uses mock detectors.
if "pytest" not in sys.modules:
    warm_up()

application = ProtocolTypeRouter({
    "http": BodyLimitMiddleware(django_asgi_app),
    "websocket": URLRouter(websocket_urlpatterns),  # Origin and token are checked in the consumers
})
