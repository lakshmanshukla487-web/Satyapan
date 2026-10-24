from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("api/v1/auth/login", views.login),
    path("api/v1/auth/register", views.register),
    path("api/v1/auth/me", views.me),
    path("api/v1/auth/logout", views.logout),
]
