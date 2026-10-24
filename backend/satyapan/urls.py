from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularSwaggerView

from apps.core.exceptions import json_404, json_500

handler404 = json_404
handler500 = json_500

urlpatterns = []
if settings.EXPOSE_API_DOCS:  # A05: the route map is not published in production unless EXPOSE_API_DOCS=true
    urlpatterns += [
        path("openapi.json", SpectacularJSONAPIView.as_view(), name="schema"),
        path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
urlpatterns += [
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.verification.urls")),
    path("", include("apps.challenges.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.voice.urls")),
    path("", include("apps.visual.urls")),
    path("", include("apps.integrity.urls")),
    path("", include("apps.biometrics.urls")),
    path("", include("apps.avsync.urls")),
    path("", include("apps.pulse.urls")),
    path("", include("apps.decision_engine.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.realtime.urls")),
    path("", include("apps.evidence.urls")),
    path("", include("apps.devlab.urls")),
]
