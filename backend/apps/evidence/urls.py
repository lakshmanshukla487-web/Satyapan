from django.urls import path

from apps.evidence import views

S = "api/v1/sessions"
urlpatterns = [
    path(f"{S}/<str:session_id>/evidence", views.evidence),
    path(f"{S}/<str:session_id>/evidence/export", views.export),
    path(f"{S}/<str:session_id>/evidence/verify", views.verify),
]
