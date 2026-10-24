from django.urls import path

from apps.biometrics import views

S = "api/v1/sessions"
urlpatterns = [
    path(f"{S}/<str:session_id>/reference-photo", views.reference_photo),
    path(f"{S}/<str:session_id>/challenges/<str:challenge_id>/eye-scan", views.eye_scan),
    path(f"{S}/<str:session_id>/biometrics", views.biometrics_summary),
]
