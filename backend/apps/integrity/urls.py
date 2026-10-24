from django.urls import path

from apps.integrity import views

urlpatterns = [path("api/v1/sessions/<str:session_id>/analysis/integrity", views.integrity)]
