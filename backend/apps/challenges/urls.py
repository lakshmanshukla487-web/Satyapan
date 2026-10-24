from django.urls import path

from apps.challenges import views

S = "api/v1/sessions"
urlpatterns = [
    path("api/v1/approvals/pending", views.pending_approvals),
    path(f"{S}/<str:session_id>/challenges", views.challenges),
    path(f"{S}/<str:session_id>/challenges/current", views.challenge_current),
    path(f"{S}/<str:session_id>/challenges/issue", views.challenge_issue),
    path(f"{S}/<str:session_id>/challenges/<str:challenge_id>/result", views.challenge_result),
    path(f"{S}/<str:session_id>/challenges/<str:challenge_id>/approve", views.challenge_approve),
    path(f"{S}/<str:session_id>/challenges/<str:challenge_id>/regenerate", views.challenge_regenerate),
]
