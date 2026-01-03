from django.urls import path

from . import views

app_name = "monitor"

urlpatterns = [
    path("", views.home, name="home"),
    path("feed/", views.feed, name="feed"),
    path("revision/<int:article_id>/", views.revision, name="revision_detail"),
    path("dashboards/", views.dashboards, name="dashboards"),
    path("dashboards/export/", views.dashboards_export, name="dashboards_export"),
    path("benchmarks/", views.benchmarks, name="benchmarks"),
    path("benchmarks/export/", views.benchmarks_export, name="benchmarks_export"),
    path("revision/", views.revision, name="revision"),
    path("procesos/", views.procesos, name="procesos"),
    path("fuentes/", views.sources, name="sources"),
    path("api/summary/", views.api_summary, name="api_summary"),
    path("api/entities", views.api_entities, name="api_entities"),
    path("api/feed", views.api_feed, name="api_feed"),
    path("api/article/<int:article_id>/", views.api_article_detail, name="api_article_detail"),
    path("api/article/<int:article_id>/review", views.api_article_review, name="api_article_review"),
    path("api/dashboard", views.api_dashboard, name="api_dashboard"),
    path("api/benchmark", views.api_benchmark, name="api_benchmark"),
    path("api/sources", views.api_sources, name="api_sources"),
    path("api/sources/test/<int:source_id>", views.api_sources_test, name="api_sources_test"),
    path("api/processes", views.api_processes, name="api_processes"),
    path("api/processes/run", views.api_process_run, name="api_process_run"),
    path("api/export/dashboard", views.api_export_dashboard, name="api_export_dashboard"),
    path("api/export/benchmark", views.api_export_benchmark, name="api_export_benchmark"),
]
