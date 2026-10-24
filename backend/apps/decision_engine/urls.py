from django.urls import path

from apps.decision_engine import views

S = "api/v1/sessions"
urlpatterns = [
    path(f"{S}/<str:session_id>/analysis", views.get_analysis),
    path(f"{S}/<str:session_id>/analysis/session", views.session_analysis),
]
