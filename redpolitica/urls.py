from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from .views import (
    PersonaListView,
    PersonaDetailView,
    PersonaGrafoView,
    grafo_persona_page,
    InstitucionGrafoView,
    grafo_institucion_page,
)

urlpatterns = [
    # PERSONAS
    path("personas/", PersonaListView.as_view(), name="persona-list"),
    path("personas/<slug:slug>/", PersonaDetailView.as_view(), name="persona-detail"),
    path("personas/<slug:slug>/grafo/", PersonaGrafoView.as_view(), name="persona-grafo"),
    path(
        "personas/<slug:slug>/grafo-page/",
        grafo_persona_page,
        name="persona-grafo-page",
    ),

    # INSTITUCIONES
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
]

urlpatterns = format_suffix_patterns(urlpatterns)

