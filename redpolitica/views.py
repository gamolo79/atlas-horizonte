from django.shortcuts import get_object_or_404, render
from django.views.generic import ListView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Cargo, Institucion, Persona, Relacion
from .serializers import InstitucionSerializer, PersonaSerializer, RelacionSerializer


def index_apps(request):
    return render(request, "redpolitica/index_apps.html")


def atlas_home(request):
    return render(request, "redpolitica/atlas_home.html")


def monitor_placeholder(request):
    return render(request, "redpolitica/app_placeholder.html", {"app_name": "Monitor"})


def social_placeholder(request):
    return render(request, "redpolitica/app_placeholder.html", {"app_name": "Social"})


class AtlasPersonasListView(ListView):
    model = Persona
    template_name = "redpolitica/atlas_personas_list.html"
    context_object_name = "personas"
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            Persona.objects.all()
            .prefetch_related("cargos__institucion")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(nombre_completo__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        return context


class AtlasInstitucionesListView(ListView):
    model = Institucion
    template_name = "redpolitica/atlas_instituciones_list.html"
    context_object_name = "instituciones"
    paginate_by = 20

    def get_queryset(self):
        queryset = Institucion.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(nombre__icontains=q)

        tipo = self.request.GET.get("tipo", "").strip()
        if tipo:
            queryset = queryset.filter(tipo=tipo)

        ambito = self.request.GET.get("ambito", "").strip()
        if ambito:
            queryset = queryset.filter(ambito__icontains=ambito)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "q": self.request.GET.get("q", ""),
                "tipo": self.request.GET.get("tipo", ""),
                "ambito": self.request.GET.get("ambito", ""),
                "tipos": Institucion.TIPO_INSTITUCION,
            }
        )
        return context


# ===========
# PERSONAS
# ===========

class PersonaListView(generics.ListAPIView):
    queryset = Persona.objects.all()
    serializer_class = PersonaSerializer


class PersonaDetailView(generics.RetrieveAPIView):
    queryset = Persona.objects.all()
    serializer_class = PersonaSerializer
    lookup_field = "slug"


class PersonaGrafoView(APIView):
    """
    API JSON para el grafo de una persona.
    Estructura:
      - persona_central
      - personas_conectadas
      - relaciones (persona <-> persona)
      - instituciones (todas las relacionadas vía cargos)
    """

    def get(self, request, slug):
        persona = get_object_or_404(Persona, slug=slug)

        persona_data = PersonaSerializer(persona).data

        # Relaciones persona <-> persona donde interviene la persona central
        relaciones = Relacion.objects.filter(
            origen=persona
        ) | Relacion.objects.filter(destino=persona)
        relaciones = relaciones.distinct()
        relaciones_data = RelacionSerializer(relaciones, many=True).data

        # Personas conectadas por esas relaciones
        personas_ids = set()
        for rel in relaciones:
            personas_ids.add(rel.origen_id)
            personas_ids.add(rel.destino_id)

        # Quitamos a la persona central del set
        personas_ids.discard(persona.id)

        personas_conectadas = Persona.objects.filter(id__in=personas_ids).distinct()
        personas_conectadas_data = PersonaSerializer(
            personas_conectadas, many=True
        ).data

        # === INSTITUCIONES RELACIONADAS (para cargos) ===
        instituciones_ids = set()

        # Cargos de la persona central
        for cargo in Cargo.objects.filter(persona=persona):
            if cargo.institucion_id:
                instituciones_ids.add(cargo.institucion_id)

        # Cargos de personas conectadas
        for p in personas_conectadas:
            for cargo in Cargo.objects.filter(persona=p):
                if cargo.institucion_id:
                    instituciones_ids.add(cargo.institucion_id)

        # Subimos por la jerarquía (padres, abuelos, etc.)
        pendientes = set(instituciones_ids)
        while pendientes:
            inst_id = pendientes.pop()
            try:
                inst = Institucion.objects.only("padre_id").get(id=inst_id)
            except Institucion.DoesNotExist:
                continue
            if inst.padre_id and inst.padre_id not in instituciones_ids:
                instituciones_ids.add(inst.padre_id)
                pendientes.add(inst.padre_id)

        instituciones = Institucion.objects.filter(id__in=instituciones_ids)
        instituciones_data = InstitucionSerializer(instituciones, many=True).data

        return Response(
            {
                "persona_central": persona_data,
                "personas_conectadas": personas_conectadas_data,
                "relaciones": relaciones_data,
                "instituciones": instituciones_data,
            }
        )


def grafo_persona_page(request, slug):
    """
    Página HTML que muestra el grafo de una persona,
    usando la API interna /api/personas/<slug>/grafo/.
    """
    persona = get_object_or_404(Persona, slug=slug)
    return render(request, "redpolitica/grafo_persona.html", {"persona": persona})


# ===========
# INSTITUCIONES
# ===========

class InstitucionGrafoView(APIView):
    """
    API JSON para el grafo de una institución.

    Estructura:
      - institucion_central
      - institucion_padre (si existe)
      - instituciones (hijas directas)
      - personas (con cargos en la institución central)
      - cargos (sólo en la institución central)
    """

    def get(self, request, slug):
        institucion = get_object_or_404(Institucion, slug=slug)

        institucion_central_data = InstitucionSerializer(institucion).data

        # Hijas directas de la institución central
        hijas_qs = Institucion.objects.filter(padre=institucion).distinct()
        hijas_data = InstitucionSerializer(hijas_qs, many=True).data

        # Cargos sólo en la institución central
        cargos_qs = Cargo.objects.filter(institucion=institucion).select_related("persona")

        cargos_data = []
        personas_ids = set()

        for c in cargos_qs:
            if c.persona_id:
                personas_ids.add(c.persona_id)
            cargos_data.append(
                {
                    "id": c.id,
                    "persona_id": c.persona_id,
                    "institucion_id": c.institucion_id,
                    "nombre_cargo": c.nombre_cargo,
                    "fecha_inicio": c.fecha_inicio,
                    "fecha_fin": c.fecha_fin,
                    "notas": c.notas,
                }
            )

        personas_qs = Persona.objects.filter(id__in=personas_ids)
        personas_data = PersonaSerializer(personas_qs, many=True).data

        # Institución padre (si existe)
        institucion_padre_data = None
        if institucion.padre:
            institucion_padre_data = InstitucionSerializer(institucion.padre).data

        return Response(
            {
                "institucion_central": institucion_central_data,
                "institucion_padre": institucion_padre_data,
                "instituciones": hijas_data,   # hijas
                "personas": personas_data,     # personas con cargos en la central
                "cargos": cargos_data,         # cargos en la central
            }
        )


def grafo_institucion_page(request, slug):
    """
    Página HTML que muestra el grafo de una institución,
    usando la API interna /api/instituciones/<slug>/grafo/.
    """
    institucion = get_object_or_404(Institucion, slug=slug)
    return render(
        request,
        "redpolitica/grafo_institucion.html",
        {"institucion": institucion},
    )
