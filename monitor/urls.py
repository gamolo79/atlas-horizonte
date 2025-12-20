from django.urls import path
from .views import monitor_health
from . import views_digest
from . import views_dashboard

urlpatterns = [
    path("health/", monitor_health, name="monitor_health"),

    path("digest/", views_digest.digest_latest, name="monitor_digest_latest"),
    path("digest/<int:y>-<int:m>-<int:d>/", views_digest.digest_by_date, name="monitor_digest_by_date"),

    # Dashboard
    path("dashboard/", views_dashboard.dashboard_home, name="monitor_dashboard_home"),

    # Clientes
    path("dashboard/clients/", views_dashboard.client_list, name="monitor_dashboard_client_list"),
    path("dashboard/clients/new/", views_dashboard.client_create, name="monitor_dashboard_client_create"),
    path("dashboard/clients/<int:client_id>/", views_dashboard.client_edit, name="monitor_dashboard_client_edit"),
    path("dashboard/clients/<int:client_id>/generate/", views_dashboard.client_generate_digest, name="monitor_dashboard_client_generate"),

    # Digests
    path("dashboard/digests/<int:digest_id>/", views_dashboard.digest_view, name="monitor_dashboard_digest_view"),

    # Ops
    path("dashboard/ops/", views_dashboard.ops_run, name="monitor_dashboard_ops"),
]
