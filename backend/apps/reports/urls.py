from django.urls import path

from apps.reports import views

urlpatterns = [
    path("api/v1/sessions/<str:session_id>/report", views.report),
    path("api/v1/sessions/<str:session_id>/report/download", views.report_download),
]
