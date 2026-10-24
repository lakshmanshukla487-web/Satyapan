from django.urls import path

from apps.documents import views

S = "api/v1/sessions"
urlpatterns = [
    path(f"{S}/<str:session_id>/documents", views.documents),
    path(f"{S}/<str:session_id>/documents/submit", views.submit),  # before the <doc_type> route
    path(f"{S}/<str:session_id>/documents/<str:doc_type>", views.upload),
]
