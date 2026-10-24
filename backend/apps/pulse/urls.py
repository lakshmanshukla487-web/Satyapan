from django.urls import path

from apps.pulse import views

urlpatterns = [path("api/v1/sessions/<str:session_id>/analysis/pulse", views.pulse)]
