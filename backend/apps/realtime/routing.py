from django.urls import path

from apps.realtime.consumers import CustomerConsumer, OfficerFeedConsumer, SessionConsumer

websocket_urlpatterns = [
    path("ws/sessions/<str:session_id>", SessionConsumer.as_asgi()),
    path("ws/officer/feed", OfficerFeedConsumer.as_asgi()),
    path("ws/customer/<str:session_id>", CustomerConsumer.as_asgi()),
]
