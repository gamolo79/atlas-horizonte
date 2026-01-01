from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from .views import (
    PersonaListView,
    PersonaDetailView,
    PersonaGrafoView,
    grafo_persona_page,
    InstitucionGrafoView,
    grafo_institucion_page,
    conteo_partidos_periodo_json,
)

urlpatterns = [
    # =================
    # PERSONAS
    # =================
    path("personas/", PersonaListView.as_view(), name="persona-list"),
    path("personas/<slug:slug>/", PersonaDetailView.as_view(), name="persona-detail"),
    path(
        "personas/<slug:slug>/grafo/",
        PersonaGrafoView.as_view(),
        name="persona-grafo",
    ),
    path(
        "personas/<slug:slug>/grafo-page/",
        grafo_persona_page,
        name="persona-grafo-page",
    ),

    # =================
    # INSTITUCIONES
    # =================
    path(
        "instituciones/<slug:slug>/grafo/",
        InstitucionGrafoView.as_view(),
        name="institucion-grafo",
    ),
    path(
        "instituciones/<slug:slug>/grafo-page/",
        grafo_institucion_page,
        name="institucion-grafo-page",
    ),

    # =================
    # PERIODOS / PARTIDOS
    # =================
    path(
        "periodos/<int:periodo_id>/conteo-partidos.json",
        conteo_partidos_periodo_json,
        name="conteo-partidos-periodo",
    ),
]

urlpatterns = format_suffix_patterns(urlpatterns)
