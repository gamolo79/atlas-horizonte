from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("redpolitica.urls")),
    path("monitor/", include("monitor.urls")),
    path("sintesis/", include("sintesis.urls")),
    path("", include("redpolitica.front_urls")),
]
