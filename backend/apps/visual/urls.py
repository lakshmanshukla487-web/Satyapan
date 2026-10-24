from django.urls import path

from apps.visual import views

urlpatterns = [path("api/v1/sessions/<str:session_id>/analysis/frame", views.frame)]
