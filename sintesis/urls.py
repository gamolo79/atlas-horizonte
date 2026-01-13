from django.urls import path

from . import views

app_name = "sintesis"

urlpatterns = [
    path("", views.home, name="home"),
    path("clientes/", views.clients, name="clients"),
    path("clientes/nuevo/", views.client_form, name="client_new"),
    path("clientes/<int:client_id>/", views.client_detail, name="client_detail"),
    path("clientes/<int:client_id>/editar/", views.client_form, name="client_edit"),
    path("clientes/<int:client_id>/reportes/", views.client_reports, name="client_reports"),
    path("clientes/<int:client_id>/generar/", views.manual_run, name="client_generate"),
    path("reportes/", views.reports, name="reports"),
    path("reportes/<int:run_id>/", views.report_detail, name="report_detail"),
    path("reportes/<int:run_id>/pdf/", views.run_pdf, name="run_pdf"),
    path("procesos/", views.procesos, name="procesos"),
]
