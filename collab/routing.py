from django.urls import path

from .consumers import TenantCollabStreamConsumer


websocket_urlpatterns = [
    path("ws/collab/stream/", TenantCollabStreamConsumer.as_asgi(), name="collab_stream"),
]
