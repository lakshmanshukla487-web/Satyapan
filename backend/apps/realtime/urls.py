from django.urls import path

from apps.realtime import views

urlpatterns = [path("api/v1/rtc/config", views.rtc_config)]
