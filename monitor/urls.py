from django.urls import path

from . import views

app_name = "monitor"

urlpatterns = [
    path("", views.home, name="home"),
    path("feed/", views.feed, name="feed"),
    path("dashboards/", views.dashboards, name="dashboards"),
    path("dashboards/export/", views.dashboards_export, name="dashboards_export"),
    path("benchmarks/", views.benchmarks, name="benchmarks"),
    path("benchmarks/export/", views.benchmarks_export, name="benchmarks_export"),
    path("revision/", views.revision, name="revision"),
    path("procesos/", views.procesos, name="procesos"),
    path("fuentes/", views.sources, name="sources"),
]
