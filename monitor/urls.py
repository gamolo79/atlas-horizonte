from django.urls import path


from monitor import views_dashboard

urlpatterns = [
    # Health & lists
    path("health/", views_dashboard.health_check, name="monitor_health"), # Moved logic to dashboard
    
    # Dashboard Home
    path("dashboard/", views_dashboard.dashboard_home, name="monitor_dashboard_home"),
    path("dashboard/home/", views_dashboard.dashboard_home, name="monitor_dashboard_home_alias"),
    
    # Articles
    path("dashboard/articles/", views_dashboard.article_list, name="monitor_dashboard_article_list"),

    # Entity Dashboards
    path("dashboard/personas/<int:entity_id>/", views_dashboard.entity_dashboard, {"entity_type": "persona"}, name="monitor_dashboard_persona_detail"),
    path("dashboard/instituciones/<int:entity_id>/", views_dashboard.entity_dashboard, {"entity_type": "institucion"}, name="monitor_dashboard_institucion_detail"),
    
    # Entity Lists
    path("dashboard/personas/", views_dashboard.entity_list, {"entity_type": "persona"}, name="monitor_dashboard_personas"),
    path("dashboard/instituciones/", views_dashboard.entity_list, {"entity_type": "institucion"}, name="monitor_dashboard_instituciones"),
    
    # Ops & Training
    path("dashboard/ops/", views_dashboard.ops_dashboard, name="monitor_dashboard_ops"),
    path("dashboard/ops/review-clusters/", views_dashboard.review_clusters, name="monitor_dashboard_review_clusters"),
    path("dashboard/training/", views_dashboard.training_dashboard, name="monitor_dashboard_training"),
    
    # API
    path("api/correct-link/", views_dashboard.api_correct_link, name="monitor_api_correct_link"),
    
    # Benchmarks
    path("dashboard/benchmark/", views_dashboard.benchmarks_view, name="monitor_dashboard_benchmark"),
    path("dashboard/instituciones/benchmark/", views_dashboard.benchmarks_view, name="monitor_dashboard_instituciones_benchmark"),
    
    # Clients
    path("dashboard/clients/", views_dashboard.clients_dashboard, name="monitor_dashboard_client_list"),
    path("dashboard/clients/<int:client_id>/", views_dashboard.client_detail, name="monitor_dashboard_client_detail"),
    path("dashboard/ingest/", views_dashboard.media_ingest_dashboard, name="monitor_dashboard_ingest"),
]
