from collections import deque

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import ListView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import InstitutionTopicForm, PersonTopicManualForm, TopicForm
from .models import (
    Cargo,
    Institucion,
    Persona,
    PeriodoAdministrativo,
    Relacion,
    Topic,
    InstitutionTopic,
    PersonTopicManual,
)
from .serializers import InstitucionSerializer, PersonaSerializer, RelacionSerializer
from .utils_grafos import (
    partido_vigente_en_fecha,
    partido_vigente_en_periodo,
    conteo_por_partido_en_periodo,
)


def index_apps(request):
    return render(request, "redpolitica/index_apps.html")


def privacy_notice(request):
    return render(request, "redpolitica/aviso_privacidad.html")


def terms_conditions(request):
    return render(request, "redpolitica/terminos_condiciones.html")


def atlas_home(request):
    return render(request, "redpolitica/atlas_home.html")


def atlas_timelines(request):
    def normalize_level(cargo):
        if cargo.institucion and cargo.institucion.tipo == "partido":
            return "partidista"

        ambito = (cargo.institucion.ambito if cargo.institucion else "") or ""
        ambito = ambito.lower()
        if "federal" in ambito:
            return "federal"
        if "estatal" in ambito:
            return "estatal"
        if "municipal" in ambito:
            return "municipal"

        if cargo.periodo and cargo.periodo.nivel:
            nivel = cargo.periodo.nivel.lower()
            if nivel in {"federal", "estatal", "municipal"}:
                return nivel

        return "otro"

    def cargo_dates(cargo, today):
        if not cargo.fecha_inicio:
            return None
        end = cargo.fecha_fin
        if not end:
            end = today
        return cargo.fecha_inicio, end

    today = timezone.now().date()

    person_topics_map = {}
    for link in PersonTopicManual.objects.select_related("topic", "person"):
        person_topics_map.setdefault(link.person_id, set()).add(link.topic.name)

    inst_topics_map = {}
    for link in InstitutionTopic.objects.select_related("topic", "institution"):
        inst_topics_map.setdefault(link.institution_id, set()).add(link.topic.name)

    personas = Persona.objects.prefetch_related(
        Prefetch(
            "cargos",
            queryset=Cargo.objects.select_related("institucion", "periodo"),
        )
    )
    instituciones = Institucion.objects.prefetch_related(
        Prefetch(
            "cargos",
            queryset=Cargo.objects.select_related("persona", "periodo"),
        )
    )

    personas_data = []
    for persona in personas:
        cargos_data = []
        persona_topics = person_topics_map.get(persona.id, set())
        for cargo in persona.cargos.all():
            dates = cargo_dates(cargo, today)
            if not dates:
                continue
            inicio, fin = dates
            inst_topics = inst_topics_map.get(cargo.institucion_id, set())
            cargos_data.append(
                {
                    "label": cargo.nombre_cargo,
                    "institucion": cargo.institucion.nombre if cargo.institucion else "—",
                    "nivel": normalize_level(cargo),
                    "inicio": inicio.isoformat(),
                    "fin": fin.isoformat(),
                    "temas": sorted(persona_topics | inst_topics),
                }
            )
        personas_data.append(
            {
                "id": persona.id,
                "nombre": persona.nombre_completo,
                "cargos": cargos_data,
            }
        )

    instituciones_data = []
    for institucion in instituciones:
        cargos_data = []
        institucion_topics = inst_topics_map.get(institucion.id, set())
        for cargo in institucion.cargos.all():
            dates = cargo_dates(cargo, today)
            if not dates:
                continue
            inicio, fin = dates
            persona_topics = person_topics_map.get(cargo.persona_id, set())
            cargos_data.append(
                {
                    "label": cargo.nombre_cargo,
                    "persona": (
                        cargo.persona.nombre_completo if cargo.persona else "—"
                    ),
                    "nivel": normalize_level(cargo),
                    "inicio": inicio.isoformat(),
                    "fin": fin.isoformat(),
                    "temas": sorted(institucion_topics | persona_topics),
                }
            )
        instituciones_data.append(
            {
                "id": institucion.id,
                "nombre": institucion.nombre,
                "cargos": cargos_data,
            }
        )

    context = {
        "timeline_data": {
            "personas": personas_data,
            "instituciones": instituciones_data,
        }
    }
    return render(request, "redpolitica/atlas_timelines.html", context)


def monitor_placeholder(request):
    return redirect("/")


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

        # Filtros opcionales (editoriales)
        periodo_id = request.GET.get("periodo_id")
        cargo_clase = request.GET.get("cargo_clase")

        periodo_obj = None
        if periodo_id:
            try:
                periodo_obj = PeriodoAdministrativo.objects.get(id=int(periodo_id))
            except (ValueError, PeriodoAdministrativo.DoesNotExist):
                periodo_obj = None

        today = timezone.now().date()

        def _cargos_filtrados_por_persona(p):
            qs = Cargo.objects.filter(persona=p).select_related("institucion", "periodo")
            if periodo_id:
                try:
                    qs = qs.filter(periodo_id=int(periodo_id))
                except ValueError:
                    pass
            if cargo_clase:
                qs = qs.filter(cargo_clase=cargo_clase)
            return qs

        cargos_central = list(_cargos_filtrados_por_persona(persona))
        periodo_contexto = periodo_obj
        fecha_contexto = None

        if not periodo_contexto and cargos_central:
            cargos_con_periodo = [c for c in cargos_central if c.periodo]
            if cargos_con_periodo:
                cargo_ref = max(
                    cargos_con_periodo,
                    key=lambda c: (c.periodo.fecha_fin, c.periodo.fecha_inicio),
                )
                periodo_contexto = cargo_ref.periodo
            else:
                fechas = [
                    f
                    for f in [c.fecha_fin or c.fecha_inicio for c in cargos_central]
                    if f
                ]
                if fechas:
                    fecha_contexto = max(fechas)

        def _party_name_for_person(person_id: int):
            if periodo_contexto:
                part = partido_vigente_en_periodo(person_id, periodo_contexto)
                return part.nombre if part else None
            ref_date = fecha_contexto or today
            part = partido_vigente_en_fecha(person_id, ref_date)
            return part.nombre if part else None

        persona_data = PersonaSerializer(persona).data
        persona_data["party"] = _party_name_for_person(persona.id)

        # Relaciones persona <-> persona hasta grado 3 (BFS)
        max_depth = 3
        personas_ids = {persona.id}
        relaciones_ids = set()

        relaciones_qs = Relacion.objects.all().select_related("origen", "destino")
        adjacency = {}

        for rel in relaciones_qs:
            adjacency.setdefault(rel.origen_id, []).append(rel)
            adjacency.setdefault(rel.destino_id, []).append(rel)

        visitados = {persona.id: 0}
        queue = deque([persona.id])

        while queue:
            actual_id = queue.popleft()
            profundidad_actual = visitados[actual_id]
            if profundidad_actual >= max_depth:
                continue

            for rel in adjacency.get(actual_id, []):
                relaciones_ids.add(rel.id)
                vecino_id = rel.destino_id if rel.origen_id == actual_id else rel.origen_id

                if vecino_id not in visitados:
                    visitados[vecino_id] = profundidad_actual + 1
                    personas_ids.add(vecino_id)
                    queue.append(vecino_id)
                else:
                    personas_ids.add(vecino_id)

        # Quitamos a la persona central del set
        personas_ids.discard(persona.id)

        personas_conectadas = Persona.objects.filter(id__in=personas_ids).distinct()
        personas_conectadas_data = PersonaSerializer(
            personas_conectadas, many=True
        ).data
        # Enriquecer con partido vigente en el periodo (para colorear)
        for d in personas_conectadas_data:
            try:
                d["party"] = _party_name_for_person(int(d["id"]))
            except Exception:
                d["party"] = None

        relaciones = Relacion.objects.filter(id__in=relaciones_ids)
        relaciones_data = RelacionSerializer(relaciones, many=True).data

        # === INSTITUCIONES RELACIONADAS (para cargos) ===
        instituciones_ids = set()

        # Cargos de la persona central
        for cargo in _cargos_filtrados_por_persona(persona):
            if cargo.institucion_id:
                instituciones_ids.add(cargo.institucion_id)

        # Cargos de personas conectadas
        for p in personas_conectadas:
            for cargo in _cargos_filtrados_por_persona(p):
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

        temas_map = {}
        tema_relaciones = []
        manual_links = PersonTopicManual.objects.filter(person=persona).select_related("topic")
        for link in manual_links:
            temas_map.setdefault(
                link.topic_id,
                {
                    "id": link.topic_id,
                    "nombre": link.topic.name,
                    "slug": link.topic.slug,
                    "topic_kind": link.topic.topic_kind,
                    "topic_kind_label": link.topic.get_topic_kind_display(),
                    "status": link.topic.status,
                },
            )
            tema_relaciones.append(
                {
                    "tema_id": link.topic_id,
                    "tipo": "manual",
                    "role": link.role,
                    "note": link.note,
                }
            )

        cargos_persona = Cargo.objects.filter(persona=persona).select_related("institucion", "periodo")
        if periodo_id:
            try:
                cargos_persona = cargos_persona.filter(periodo_id=int(periodo_id))
            except ValueError:
                pass
        if cargo_clase:
            cargos_persona = cargos_persona.filter(cargo_clase=cargo_clase)

        temas_cargo_vistos = set()
        for cargo in cargos_persona:
            if not cargo.institucion_id:
                continue
            inst_topics = InstitutionTopic.objects.filter(
                institution=cargo.institucion
            ).select_related("topic")
            for inst_topic in inst_topics:
                temas_map.setdefault(
                    inst_topic.topic_id,
                    {
                        "id": inst_topic.topic_id,
                        "nombre": inst_topic.topic.name,
                        "slug": inst_topic.topic.slug,
                        "topic_kind": inst_topic.topic.topic_kind,
                        "topic_kind_label": inst_topic.topic.get_topic_kind_display(),
                        "status": inst_topic.topic.status,
                    },
                )
                rel_key = (inst_topic.topic_id, cargo.id)
                if rel_key in temas_cargo_vistos:
                    continue
                temas_cargo_vistos.add(rel_key)
                tema_relaciones.append(
                    {
                        "tema_id": inst_topic.topic_id,
                        "tipo": "heredado",
                        "role": inst_topic.role,
                        "institucion_id": cargo.institucion_id,
                        "cargo_id": cargo.id,
                        "cargo_nombre": cargo.nombre_cargo,
                        "cargo_clase": getattr(cargo, "cargo_clase", None),
                        "cargo_titulo": getattr(cargo, "cargo_titulo", None) or cargo.nombre_cargo,
                        "periodo_id": cargo.periodo_id,
                        "periodo_nombre": cargo.periodo.nombre if cargo.periodo else None,
                        "fecha_inicio": cargo.fecha_inicio,
                        "fecha_fin": cargo.fecha_fin,
                    }
                )

        return Response(
            {
                "persona_central": persona_data,
                "personas_conectadas": personas_conectadas_data,
                "relaciones": relaciones_data,
                "instituciones": instituciones_data,
                "temas": list(temas_map.values()),
                "tema_relaciones": tema_relaciones,
                "meta": {
                    "periodo_id": int(periodo_id) if (periodo_id and str(periodo_id).isdigit()) else None,
                    "cargo_clase": cargo_clase or None,
                },
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
      - instituciones_nivel2 (hijas de las hijas)
      - instituciones_ancestros (cadena hasta la raíz)
      - personas (con cargos en la institución central)
      - cargos (sólo en la institución central)
    """

    def get(self, request, slug):
        institucion = get_object_or_404(Institucion, slug=slug)

        # Filtros opcionales (editoriales)
        periodo_id = request.GET.get("periodo_id")
        cargo_clase = request.GET.get("cargo_clase")

        today = timezone.now().date()

        institucion_central_data = InstitucionSerializer(institucion).data

        # Hijas directas de la institución central
        hijas_qs = Institucion.objects.filter(padre=institucion).distinct()
        hijas_data = InstitucionSerializer(hijas_qs, many=True).data

        # Nietas (hijas de las hijas) para nivel 3
        nietas_qs = Institucion.objects.filter(padre__in=hijas_qs).distinct()
        nietas_data = InstitucionSerializer(nietas_qs, many=True).data

        # Cargos sólo en la institución central
        cargos_qs = Cargo.objects.filter(institucion=institucion).select_related(
            "persona",
            "periodo",
        )
        if periodo_id:
            try:
                cargos_qs = cargos_qs.filter(periodo_id=int(periodo_id))
            except ValueError:
                pass
        if cargo_clase:
            cargos_qs = cargos_qs.filter(cargo_clase=cargo_clase)

        cargos_data = []
        personas_ids = set()
        persona_context = {}

        def _cargo_context(cargo):
            if cargo.periodo:
                return {
                    "periodo": cargo.periodo,
                    "fecha": None,
                    "sort_date": cargo.periodo.fecha_fin or cargo.periodo.fecha_inicio or today,
                }
            fecha = cargo.fecha_fin or cargo.fecha_inicio or today
            return {"periodo": None, "fecha": fecha, "sort_date": fecha}

        for c in cargos_qs:
            if c.persona_id:
                personas_ids.add(c.persona_id)
                contexto = _cargo_context(c)
                previo = persona_context.get(c.persona_id)
                if not previo or contexto["sort_date"] > previo["sort_date"]:
                    persona_context[c.persona_id] = contexto
            cargos_data.append(
                {
                    "id": c.id,
                    "persona_id": c.persona_id,
                    "institucion_id": c.institucion_id,
                    "nombre_cargo": c.nombre_cargo,
                    "cargo_clase": getattr(c, "cargo_clase", None),
                    "cargo_titulo": getattr(c, "cargo_titulo", None) or c.nombre_cargo,
                    "periodo_id": c.periodo_id,
                    "periodo_nombre": c.periodo.nombre if c.periodo else None,
                    "fecha_inicio": c.fecha_inicio,
                    "fecha_fin": c.fecha_fin,
                    "notas": c.notas,
                }
            )

        personas_qs = Persona.objects.filter(id__in=personas_ids)
        personas_data = PersonaSerializer(personas_qs, many=True).data
        # Enriquecer con partido vigente en el periodo (para colorear)
        for d in personas_data:
            try:
                contexto = persona_context.get(int(d["id"]))
                part = None
                if contexto and contexto["periodo"]:
                    part = partido_vigente_en_periodo(int(d["id"]), contexto["periodo"])
                else:
                    fecha_ref = contexto["fecha"] if contexto else today
                    part = partido_vigente_en_fecha(int(d["id"]), fecha_ref)
                d["party"] = part.nombre if part else None
            except Exception:
                d["party"] = None

        # Institución padre (si existe)
        institucion_padre_data = None
        if institucion.padre:
            institucion_padre_data = InstitucionSerializer(institucion.padre).data

        # Ancestros hasta la raíz para dibujar organigrama
        ancestros_data = []
        actual = institucion.padre
        visitados = set()
        while actual and actual.id not in visitados:
            ancestros_data.append(InstitucionSerializer(actual).data)
            visitados.add(actual.id)
            actual = actual.padre

        temas_map = {}
        tema_relaciones = []
        inst_links = InstitutionTopic.objects.filter(
            institution=institucion
        ).select_related("topic")
        for link in inst_links:
            temas_map.setdefault(
                link.topic_id,
                {
                    "id": link.topic_id,
                    "nombre": link.topic.name,
                    "slug": link.topic.slug,
                    "topic_kind": link.topic.topic_kind,
                    "topic_kind_label": link.topic.get_topic_kind_display(),
                    "status": link.topic.status,
                },
            )
            tema_relaciones.append(
                {
                    "tema_id": link.topic_id,
                    "tipo": "institucion",
                    "role": link.role,
                    "note": link.note,
                    "valid_from": link.valid_from,
                    "valid_to": link.valid_to,
                }
            )

        return Response(
            {
                "institucion_central": institucion_central_data,
                "institucion_padre": institucion_padre_data,
                "instituciones": hijas_data,          # hijas
                "instituciones_nivel2": nietas_data,  # hijas de las hijas
                "instituciones_ancestros": ancestros_data,  # cadena de padres
                "personas": personas_data,              # personas con cargos en la central
                "cargos": cargos_data,                  # cargos en la central (filtrables)
                "temas": list(temas_map.values()),
                "tema_relaciones": tema_relaciones,
                "meta": {
                    "periodo_id": int(periodo_id) if (periodo_id and str(periodo_id).isdigit()) else None,
                    "cargo_clase": cargo_clase or None,
                },
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


def conteo_partidos_periodo_json(request, periodo_id):
    """
    Conteo de personas por partido vigente dentro de un periodo,
    filtrando por cargo_clase (puede venir repetido en querystring).

    Ejemplos:
      /api/periodos/20/conteo-partidos.json?cargo_clase=diputacion_local
      /api/periodos/2/conteo-partidos.json?cargo_clase=senaduria&cargo_clase=diputacion_federal
    """
    cargo_clases = request.GET.getlist("cargo_clase")
    if not cargo_clases:
        cargo_clases = ["diputacion_local", "diputacion_federal", "senaduria"]

    data = conteo_por_partido_en_periodo(int(periodo_id), cargo_clases)
    return JsonResponse(
        {
            "periodo_id": int(periodo_id),
            "cargo_clases": cargo_clases,
            "conteo": data,
        }
    )


# ===========
# TEMAS
# ===========


def atlas_topics_list(request):
    topics = Topic.objects.select_related("parent").prefetch_related("children")
    q = request.GET.get("q", "").strip()
    if q:
        topics = topics.filter(name__icontains=q)

    kind = request.GET.get("kind", "").strip()
    if kind:
        topics = topics.filter(topic_kind=kind)

    status = request.GET.get("status", "").strip()
    if status:
        topics = topics.filter(status=status)

    view_mode = request.GET.get("view", "list")
    topics_tree = None
    if view_mode == "tree":
        topics_tree = topics.filter(parent__isnull=True).prefetch_related("children")

    context = {
        "topics": topics,
        "topics_tree": topics_tree,
        "q": q,
        "kind": kind,
        "status": status,
        "view": view_mode,
        "kind_choices": Topic.TOPIC_KIND_CHOICES,
        "status_choices": Topic.STATUS_CHOICES,
    }
    return render(request, "redpolitica/atlas_topics_list.html", context)


@staff_member_required
def atlas_topic_create(request):
    if request.method == "POST":
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save()
            messages.success(request, "Tema creado correctamente.")
            return redirect("atlas-topic-detail", slug=topic.slug)
    else:
        form = TopicForm()
    return render(
        request,
        "redpolitica/atlas_topic_form.html",
        {"form": form, "is_edit": False},
    )


@staff_member_required
def atlas_topic_edit(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    if request.method == "POST":
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            topic = form.save()
            messages.success(request, "Tema actualizado correctamente.")
            return redirect("atlas-topic-detail", slug=topic.slug)
    else:
        form = TopicForm(instance=topic)
    return render(
        request,
        "redpolitica/atlas_topic_form.html",
        {"form": form, "topic": topic, "is_edit": True},
    )


def atlas_topic_detail(request, slug):
    topic = get_object_or_404(
        Topic.objects.select_related("parent").prefetch_related("children"),
        slug=slug,
    )

    breadcrumb = []
    current = topic.parent
    while current:
        breadcrumb.append(current)
        current = current.parent
    breadcrumb.reverse()

    context = {
        "topic": topic,
        "breadcrumb": breadcrumb,
        "children": topic.children.all(),
    }
    return render(request, "redpolitica/atlas_topic_detail.html", context)


@staff_member_required
def atlas_topic_link_institution(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    if request.method != "POST":
        return redirect("atlas-topic-detail", slug=topic.slug)
    form = InstitutionTopicForm(request.POST)
    if form.is_valid():
        link = form.save(commit=False)
        link.topic = topic
        try:
            link.save()
            messages.success(request, "Institución vinculada al tema.")
        except IntegrityError:
            messages.error(request, "Ya existe un vínculo con esa institución y rol.")
    else:
        messages.error(request, "Revisa los datos del formulario de institución.")
    return redirect("atlas-topic-detail", slug=topic.slug)


@staff_member_required
def atlas_topic_link_person(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    if request.method != "POST":
        return redirect("atlas-topic-detail", slug=topic.slug)
    form = PersonTopicManualForm(request.POST)
    if form.is_valid():
        link = form.save(commit=False)
        link.topic = topic
        try:
            link.save()
            messages.success(request, "Persona vinculada al tema.")
        except IntegrityError:
            messages.error(request, "Ya existe un vínculo con esa persona y rol.")
    else:
        messages.error(request, "Revisa los datos del formulario de persona.")
    return redirect("atlas-topic-detail", slug=topic.slug)


@staff_member_required
def atlas_topic_unlink_institution(request, slug, link_id):
    topic = get_object_or_404(Topic, slug=slug)
    link = get_object_or_404(InstitutionTopic, id=link_id, topic=topic)
    if request.method == "POST":
        link.delete()
        messages.success(request, "Vínculo con institución eliminado.")
    return redirect("atlas-topic-detail", slug=topic.slug)


@staff_member_required
def atlas_topic_unlink_person(request, slug, link_id):
    topic = get_object_or_404(Topic, slug=slug)
    link = get_object_or_404(PersonTopicManual, id=link_id, topic=topic)
    if request.method == "POST":
        link.delete()
        messages.success(request, "Vínculo con persona eliminado.")
    return redirect("atlas-topic-detail", slug=topic.slug)


def atlas_topic_graph_json(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    include_hierarchy = request.GET.get("hierarchy") in {"1", "true", "True"}

    nodes = [
        {
            "id": f"topic:{topic.id}",
            "label": topic.name,
            "type": "topic",
            "slug": topic.slug,
            "topic_kind": topic.topic_kind,
            "topic_kind_label": topic.get_topic_kind_display(),
            "status": topic.status,
            "status_label": topic.get_status_display(),
            "description": topic.description,
        }
    ]
    edges = []
    node_ids = {f"topic:{topic.id}"}

    institution_links = InstitutionTopic.objects.filter(topic=topic).select_related(
        "institution"
    )
    for link in institution_links:
        inst = link.institution
        node_id = f"inst:{inst.id}"
        if node_id not in node_ids:
            nodes.append(
                {
                    "id": node_id,
                    "label": inst.nombre,
                    "type": "institution",
                    "slug": inst.slug,
                    "tipo": inst.tipo,
                    "ambito": inst.ambito,
                    "ciudad": inst.ciudad,
                    "estado": inst.estado,
                    "pais": inst.pais,
                }
            )
            node_ids.add(node_id)
        edges.append(
            {
                "source": f"topic:{topic.id}",
                "target": node_id,
                "label": link.role,
                "type": "institution_topic",
            }
        )

    person_manual_links = PersonTopicManual.objects.filter(topic=topic).select_related(
        "person"
    )
    for link in person_manual_links:
        person = link.person
        node_id = f"person:{person.id}"
        if node_id not in node_ids:
            nodes.append(
                {
                    "id": node_id,
                    "label": person.nombre_completo,
                    "type": "person",
                    "slug": person.slug,
                    "bio_corta": person.bio_corta,
                }
            )
            node_ids.add(node_id)
        edges.append(
            {
                "source": f"topic:{topic.id}",
                "target": node_id,
                "label": link.role,
                "type": "person_topic_manual",
            }
        )

    instituciones = Institucion.objects.filter(temas_relacionados__topic=topic).distinct()
    inherited_cargos = Cargo.objects.filter(institucion__in=instituciones).select_related(
        "persona",
        "institucion",
    )
    inherited_pairs = set()
    for cargo in inherited_cargos:
        person = cargo.persona
        if not person:
            continue
        node_id = f"person:{person.id}"
        if node_id not in node_ids:
            nodes.append(
                {
                    "id": node_id,
                    "label": person.nombre_completo,
                    "type": "person",
                    "slug": person.slug,
                    "bio_corta": person.bio_corta,
                }
            )
            node_ids.add(node_id)
        edge_key = (person.id, cargo.id)
        if edge_key in inherited_pairs:
            continue
        inherited_pairs.add(edge_key)
        edges.append(
            {
                "source": f"topic:{topic.id}",
                "target": node_id,
                "label": "por cargo",
                "type": "person_topic_inherited",
                "cargo": cargo.nombre_cargo,
                "institucion": cargo.institucion.nombre if cargo.institucion else None,
                "fecha_inicio": cargo.fecha_inicio,
                "fecha_fin": cargo.fecha_fin,
            }
        )

    if include_hierarchy:
        if topic.parent:
            parent = topic.parent
            node_id = f"topic:{parent.id}"
            if node_id not in node_ids:
                nodes.append(
                    {
                        "id": node_id,
                        "label": parent.name,
                        "type": "topic_parent",
                        "slug": parent.slug,
                        "topic_kind": parent.topic_kind,
                        "topic_kind_label": parent.get_topic_kind_display(),
                        "status": parent.status,
                        "status_label": parent.get_status_display(),
                        "description": parent.description,
                    }
                )
                node_ids.add(node_id)
            edges.append(
                {
                    "source": f"topic:{parent.id}",
                    "target": f"topic:{topic.id}",
                    "label": "padre",
                    "type": "topic_hierarchy",
                }
            )
        for child in topic.children.all():
            node_id = f"topic:{child.id}"
            if node_id not in node_ids:
                nodes.append(
                    {
                        "id": node_id,
                        "label": child.name,
                        "type": "topic_child",
                        "slug": child.slug,
                        "topic_kind": child.topic_kind,
                        "topic_kind_label": child.get_topic_kind_display(),
                        "status": child.status,
                        "status_label": child.get_status_display(),
                        "description": child.description,
                    }
                )
                node_ids.add(node_id)
            edges.append(
                {
                    "source": f"topic:{topic.id}",
                    "target": f"topic:{child.id}",
                    "label": "hijo",
                    "type": "topic_hierarchy",
                }
            )

    return JsonResponse(
        {
            "nodes": nodes,
            "edges": edges,
            "meta": {"topic_id": topic.id},
        }
    )
