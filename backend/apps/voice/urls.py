from django.urls import path

from apps.voice import views

urlpatterns = [path("api/v1/sessions/<str:session_id>/analysis/audio", views.audio)]
