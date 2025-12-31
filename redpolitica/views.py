from collections import deque
from datetime import date

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import InstitutionTopicForm, PersonTopicManualForm, TopicForm
from .models import (
    Cargo,
    Institucion,
    Persona,
    Relacion,
    Topic,
    InstitutionTopic,
    PersonTopicManual,
)
from .serializers import InstitucionSerializer, PersonaSerializer, RelacionSerializer


def index_apps(request):
    return render(request, "redpolitica/index_apps.html")


def privacy_notice(request):
    return render(request, "redpolitica/aviso_privacidad.html")


def terms_conditions(request):
    return render(request, "redpolitica/terminos_condiciones.html")


def atlas_home(request):
    return render(request, "redpolitica/atlas_home.html")


def atlas_timelines(request):
    entity_type = request.GET.get("tipo", "persona")
    entity_id = request.GET.get("entidad_id", "").strip()
    include_children = request.GET.get("incluir_hijas") == "1"
    current_date = date.today()

    personas = Persona.objects.all().order_by("nombre_completo")
    instituciones = Institucion.objects.all().order_by("nombre")

    selected_entity = None
    import json
    from django.core.serializers.json import DjangoJSONEncoder

    personas = Persona.objects.all().order_by("nombre_completo")
    instituciones = Institucion.objects.all().order_by("nombre")

    # Helper functions for the view
    def infer_level(cargo):
        if not cargo.institucion_id:
            return "otro"
        tipo = (cargo.institucion.tipo or "").lower()
        ambito = (cargo.institucion.ambito or "").lower()
        if "partido" in tipo or "partid" in ambito:
            return "partidista"
        if "federal" in ambito or "nacional" in ambito:
            return "federal"
        if "municipal" in ambito or "municipio" in ambito:
            return "municipal"
        if "estatal" in ambito:
            return "estatal"
        return "otro"

    def normalize_dates(cargo):
        start_value = cargo.fecha_inicio or (
            cargo.periodo.fecha_inicio if cargo.periodo_id else None
        )
        end_value = cargo.fecha_fin or (
            cargo.periodo.fecha_fin if cargo.periodo_id else None
        )
        if cargo.es_actual and not end_value:
            end_value = current_date
        if start_value and not end_value:
            end_value = start_value
        return start_value, end_value

    entity_items = []
    
    if entity_id:
        if entity_type == "institucion":
            selected_entity = get_object_or_404(Institucion, id=entity_id)
            cargos = (
                Cargo.objects.filter(institucion=selected_entity)
                .select_related("persona", "institucion", "periodo")
                .order_by("fecha_inicio")
            )
            # If "include_children", fetch children institutions and their cargos too?
            # The mockup implies we just show people in THIS institution or related?
            # For now, let's keep it simple: just this institution's cargos.
            # If the user selected "incluir hijas", we'd need recursion again.
            
            if include_children:
                instituciones_ids = [selected_entity.id]
                pendientes = [selected_entity.id]
                while pendientes:
                    current_id = pendientes.pop()
                    for child in Institucion.objects.filter(padre_id=current_id).only("id"):
                        if child.id not in instituciones_ids:
                            instituciones_ids.append(child.id)
                            pendientes.append(child.id)
                # Re-fetch with all ids
                cargos = (
                    Cargo.objects.filter(institucion_id__in=instituciones_ids)
                    .select_related("persona", "institucion", "periodo")
                    .order_by("fecha_inicio")
                )

            for cargo in cargos:
                start_value, end_value = normalize_dates(cargo)
                if not start_value or not end_value:
                    continue
                
                # We pass dates as strings YYYY-MM-DD
                entity_items.append({
                    "label": cargo.nombre_cargo,
                    "persona": cargo.persona.nombre_completo,
                    "nivel": infer_level(cargo),
                    "inicio": start_value.strftime("%Y-%m-%d"),
                    "fin": end_value.strftime("%Y-%m-%d"),
                    "institucion": cargo.institucion.nombre,
                })
                
        else:
            selected_entity = get_object_or_404(Persona, id=entity_id)
            # Fetch all cargos for this person
            cargos = (
                Cargo.objects.filter(persona=selected_entity)
                .select_related("institucion", "periodo")
                .order_by("fecha_inicio")
            )
            for cargo in cargos:
                start_value, end_value = normalize_dates(cargo)
                if not start_value or not end_value:
                    continue
                
                entity_items.append({
                    "label": cargo.nombre_cargo,
                    "institucion": cargo.institucion.nombre if cargo.institucion else "Sin Institución",
                    "nivel": infer_level(cargo),
                    "inicio": start_value.strftime("%Y-%m-%d"),
                    "fin": end_value.strftime("%Y-%m-%d"),
                })

    # Prepare JSON structure for the frontend
    # It mimics the mocked "DATA" structure but flat enough to just be used directly
    entity_data = {
        "type": entity_type,
        "selected_id": entity_id,
        "items": entity_items
    }
    
    entity_data_json = json.dumps(entity_data, cls=DjangoJSONEncoder)

    context = {
        "personas": personas,
        "instituciones": instituciones,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "include_children": include_children,
        "selected_entity": selected_entity,
        "entity_data_json": entity_data_json, # <--- The new magic
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

        persona_data = PersonaSerializer(persona).data

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

        relaciones = Relacion.objects.filter(id__in=relaciones_ids)
        relaciones_data = RelacionSerializer(relaciones, many=True).data

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

        cargos_persona = Cargo.objects.filter(persona=persona).select_related("institucion")
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
                    "periodo_id": c.periodo_id,
                    "periodo_nombre": c.periodo.nombre if c.periodo else None,
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
                "cargos": cargos_data,                  # cargos en la central
                "temas": list(temas_map.values()),
                "tema_relaciones": tema_relaciones,
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
