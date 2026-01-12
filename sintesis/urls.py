from django.urls import path

from . import views

app_name = "sintesis"

urlpatterns = [
    path("", views.home, name="home"),
    path("clientes/", views.clients, name="clients"),
    path("clientes/<int:client_id>/", views.client_detail, name="client_detail"),
    path("clientes/<int:client_id>/sintesis/", views.client_stories, name="client_stories"),
    path("procesos/", views.procesos, name="procesos"),
    path("reporte/<int:run_id>/", views.run_report, name="run_report"),
]
