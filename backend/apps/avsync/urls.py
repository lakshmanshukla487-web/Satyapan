from django.urls import path

from apps.avsync import views

urlpatterns = [path("api/v1/sessions/<str:session_id>/analysis/avsync", views.avsync)]
