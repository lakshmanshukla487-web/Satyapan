from django.urls import path

from apps.core import views

urlpatterns = [
    path("health", views.health),
    path("health/ready", views.ready),
    path("api/v1/models/status", views.models_status),
]
