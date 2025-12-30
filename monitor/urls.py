from django.urls import path

from monitor import views

urlpatterns = [
    path("health/", views.monitor_health, name="monitor_health"),
    path("ingest/", views.ingest_list, name="monitor_ingest"),
    path("articles/<int:article_id>/", views.article_correction, name="monitor_article_correction"),
    path("stories/<int:story_id>/", views.story_correction, name="monitor_story_correction"),
    path("dashboard/", views.dashboard_view, name="monitor_dashboard"),
    path("dashboard/<str:entity_type>/<str:atlas_id>/", views.dashboard_entity_view, name="monitor_dashboard_entity"),
    path("benchmarks/", views.benchmarks_view, name="monitor_benchmarks"),
    path("benchmarks/export/pdf/", views.export_pdf_placeholder, name="monitor_benchmarks_export"),
    path("api/jobs/ingest/", views.api_job_ingest, name="monitor_api_ingest"),
    path("api/jobs/analyze/", views.api_job_analyze, name="monitor_api_analyze"),
    path("api/jobs/cluster/", views.api_job_cluster, name="monitor_api_cluster"),
    path("api/jobs/digest/", views.api_job_digest, name="monitor_api_digest"),
    path("dashboard/home/", views.dashboard_home, name="monitor_dashboard_home"),
    path("dashboard/personas/", views.personas_placeholder, name="monitor_dashboard_personas"),
    path("dashboard/instituciones/", views.instituciones_placeholder, name="monitor_dashboard_instituciones"),
    path("dashboard/benchmark/", views.benchmarks_view, name="monitor_dashboard_benchmark"),
    path(
        "dashboard/instituciones/benchmark/",
        views.benchmarks_view,
        name="monitor_dashboard_instituciones_benchmark",
    ),
    path("dashboard/ingest/", views.ingest_list, name="monitor_dashboard_ingest"),
    path("dashboard/clients/", views.clients_placeholder, name="monitor_dashboard_client_list"),
    path("dashboard/training/", views.training_placeholder, name="monitor_dashboard_training"),
    path("dashboard/ops/", views.ops_placeholder, name="monitor_dashboard_ops"),
]
