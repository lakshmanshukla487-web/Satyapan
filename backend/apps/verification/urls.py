from django.urls import path

from apps.verification import views

S = "api/v1/sessions"
urlpatterns = [
    path("api/v1/officer/dashboard", views.officer_dashboard),
    path(S, views.sessions),
    path(f"{S}/<str:session_id>", views.session_detail),
    path(f"{S}/<str:session_id>/consent", views.consent),
    path(f"{S}/<str:session_id>/start", views.start),
    path(f"{S}/<str:session_id>/complete", views.complete),
    path(f"{S}/<str:session_id>/finish", views.finish),
    path(f"{S}/<str:session_id>/cancel", views.cancel),
    path(f"{S}/<str:session_id>/terminate", views.terminate),
    path(f"{S}/<str:session_id>/approve", views.approve),
    path(f"{S}/<str:session_id>/reject", views.reject),
    path(f"{S}/<str:session_id>/auto-approve", views.auto_approve),
]
