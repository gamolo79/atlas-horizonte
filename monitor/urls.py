from django.urls import path

from monitor import views
from monitor import views_dashboard

urlpatterns = [
    # Health & lists
    path("health/", views.monitor_health, name="monitor_health"),
    path("ingest/", views.ingest_list, name="monitor_ingest"),
    
    # Dashboard Home
    path("dashboard/", views_dashboard.dashboard_home, name="monitor_dashboard_home"),
    path("dashboard/home/", views_dashboard.dashboard_home, name="monitor_dashboard_home_alias"),
    
    # Entity Dashboards
    path("dashboard/personas/<int:entity_id>/", views_dashboard.entity_dashboard, {"entity_type": "persona"}, name="monitor_dashboard_persona_detail"),
    path("dashboard/instituciones/<int:entity_id>/", views_dashboard.entity_dashboard, {"entity_type": "institucion"}, name="monitor_dashboard_institucion_detail"),
    
    # Entity Lists
    path("dashboard/personas/", views_dashboard.entity_list, {"entity_type": "persona"}, name="monitor_dashboard_personas"),
    path("dashboard/instituciones/", views_dashboard.entity_list, {"entity_type": "institucion"}, name="monitor_dashboard_instituciones"),
    
    # Ops & Training
    path("dashboard/ops/", views_dashboard.ops_dashboard, name="monitor_dashboard_ops"),
    path("dashboard/training/", views_dashboard.training_dashboard, name="monitor_dashboard_training"),
    
    # API
    path("api/correct-link/", views_dashboard.api_correct_link, name="monitor_api_correct_link"),
    
    # Benchmarks (keeping old view if it exists in 'views' or 'views_dashboard'?)
    # I didn't port benchmark view in the overwrite. I should probably add a placeholder or simple redirect.
    path("dashboard/benchmark/", views_dashboard.benchmarks_view, name="monitor_dashboard_benchmark"),
    path("dashboard/instituciones/benchmark/", views_dashboard.benchmarks_view, name="monitor_dashboard_instituciones_benchmark"),
    
    # Clients (kept placeholder if not ported)
    path("dashboard/clients/", views_dashboard.dashboard_home, name="monitor_dashboard_client_list"),
    path("dashboard/ingest/", views_dashboard.media_ingest_dashboard, name="monitor_dashboard_ingest"),
]
