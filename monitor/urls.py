from django.urls import path

from monitor import views_dashboard

urlpatterns = [
    path("dashboard/", views_dashboard.dashboard_home, name="monitor_dashboard_home"),
    path("dashboard/ingest/", views_dashboard.media_ingest_dashboard, name="monitor_dashboard_ingest"),
    path("dashboard/articles/", views_dashboard.article_list, name="monitor_dashboard_article_list"),
    path("dashboard/ops/", views_dashboard.ops_dashboard, name="monitor_dashboard_ops"),
]
