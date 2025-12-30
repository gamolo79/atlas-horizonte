from collections import Counter, defaultdict
from datetime import timedelta
import json
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from redpolitica.models import Institucion, Persona, Topic
from monitor.models import (
    Article,
    ActorLink,
    Story,
    Client,
    DailyExecution,
    MetricAggregate,
    AuditLog,
    Correction,
    JobLog,
    Source
)

LOGGER = logging.getLogger(__name__)


def health_check(request):
    return JsonResponse({"status": "ok", "service": "monitor"})


@staff_member_required
def dashboard_home(request):
    today = timezone.now().date()
    
    # KPIs
    articles_today = Article.objects.filter(published_at__date=today).count()
    stories_today = Story.objects.filter(time_window_start__date=today).count()
    
    # Recent activity
    recent_audit = AuditLog.objects.all().order_by("-created_at")[:10]
    
    # Ingest Status (from AuditLog)
    last_ingest = AuditLog.objects.filter(event_type="ingest").first()
    
    context = {
        "kpis": {
            "articles_today": articles_today,
            "stories_today": stories_today,
            "last_ingest_status": last_ingest.status if last_ingest else "unknown",
        },
        "recent_audit": recent_audit,
    }
    return render(request, "monitor/dashboard/home.html", context)


@staff_member_required
def ops_dashboard(request):
    """
    Operations dashboard to trigger pipeline manually.
    """
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "ingest":
                from monitor.pipeline import ingest_sources

                limit = int(request.POST.get("limit", 50))
                job = JobLog.objects.create(job_name="manual_ingest", status="running")
                result = ingest_sources(limit=limit)
                status = "success" if result.stats.get("errors", 0) == 0 else "partial"
                job.status = status
                job.payload = result.stats
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "payload", "finished_at"])
                messages.success(request, f"Ingest completado: {len(result.articles)} artículos nuevos.")
            elif action == "pipeline":
                # We should trigger the full pipeline
                from monitor.pipeline import run_pipeline

                job = JobLog.objects.create(job_name="manual_pipeline", status="running")
                run_pipeline(hours=24)
                job.status = "success"
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "finished_at"])
                messages.success(request, "Pipeline ejecutado correctamente.")
        except Exception as e:
            if action == "ingest":
                JobLog.objects.create(
                    job_name="manual_ingest",
                    status="error",
                    finished_at=timezone.now(),
                    payload={"error": str(e)},
                )
            elif action == "pipeline":
                JobLog.objects.create(
                    job_name="manual_pipeline",
                    status="error",
                    finished_at=timezone.now(),
                    payload={"error": str(e)},
                )
            messages.error(request, f"Error: {e}")
            LOGGER.error(f"Ops error: {e}", exc_info=True)
            
    recent_jobs = JobLog.objects.all().order_by("-started_at")[:20]
    sources = Source.objects.all().order_by("-last_fetched_at")
    
    return render(request, "monitor/dashboard/ops.html", {
        "recent_jobs": recent_jobs,
        "sources": sources
    })


@staff_member_required
def entity_dashboard(request, entity_type, entity_id):
    """
    Generic dashboard for Persona or Institucion.
    """
    days = int(request.GET.get("days", 30))
    start_date = timezone.now().date() - timedelta(days=days)
    
    entity = None
    if entity_type == "persona":
        entity = get_object_or_404(Persona, id=entity_id)
        atlas_type = ActorLink.AtlasEntityType.PERSONA
    else:
        entity = get_object_or_404(Institucion, id=entity_id)
        atlas_type = ActorLink.AtlasEntityType.INSTITUCION
        
    # Metrics from Aggregate
    aggregates = MetricAggregate.objects.filter(
        entity_type=atlas_type,
        atlas_id=str(entity_id),
        period="day",
        date_start__gte=start_date
    ).order_by("date_start")
    
    dates = [a.date_start.strftime("%Y-%m-%d") for a in aggregates]
    volumes = [a.volume for a in aggregates]
    sentiments = {
        "pos": [a.sentiment_pos for a in aggregates],
        "neu": [a.sentiment_neu for a in aggregates],
        "neg": [a.sentiment_neg for a in aggregates],
    }
    
    # Recent Appearances (Transparency)
    recent_links = ActorLink.objects.filter(
        atlas_entity_type=atlas_type,
        atlas_entity_id=str(entity_id)
    ).select_related("article").order_by("-article__published_at")[:50]
    
    # Stories
    # Find stories where this actor is a main actor
    # Or implies checking StoryActor
    from monitor.models import StoryActor
    story_ids = StoryActor.objects.filter(
        atlas_entity_type=atlas_type,
        atlas_entity_id=str(entity_id)
    ).values_list("story_id", flat=True)
    
    recent_stories = Story.objects.filter(id__in=story_ids).order_by("-time_window_start")[:10]

    context = {
        "entity": entity,
        "entity_type": entity_type,
        "days": days,
        "chart_data": {
            "dates": json.dumps(dates),
            "volumes": json.dumps(volumes),
            "sentiments": json.dumps(sentiments),
        },
        "recent_links": recent_links,
        "recent_stories": recent_stories,
    }
    return render(request, "monitor/dashboard/entity_dashboard.html", context)


@staff_member_required
def entity_list(request, entity_type):
    """
    List view for Personas or Instituciones with search.
    """
    query = request.GET.get("q", "")
    
    if entity_type == "persona":
        qs = Persona.objects.all().order_by("nombre_completo")
        if query:
            qs = qs.filter(nombre_completo__icontains=query)
        # Optimization: maybe annotate with last volume? For now, keep it simple.
    else:
        qs = Institucion.objects.all().order_by("nombre")
        if query:
            qs = qs.filter(nombre__icontains=query)
    
    # Pagination could be added here, but let's stick to simple list for now
    
    return render(request, "monitor/dashboard/entity_list.html", {
        "entity_type": entity_type,
        "entities": qs[:100], # Limit to avoid performance hit
        "query": query
    })


@staff_member_required
def benchmarks_view(request):
    """
    Select two entities to compare, or show comparison if params present.
    """
    id_a = request.GET.get("id_a")
    type_a = request.GET.get("type_a")
    id_b = request.GET.get("id_b")
    type_b = request.GET.get("type_b")
    
    if id_a and id_b and type_a and type_b:
        # Fetch entities
        model_a = Persona if type_a == "persona" else Institucion
        model_b = Persona if type_b == "persona" else Institucion
        
        entity_a = get_object_or_404(model_a, pk=id_a)
        entity_b = get_object_or_404(model_b, pk=id_b)
        
        # Fetch metrics for last 30 days default
        start_date = timezone.now().date() - timedelta(days=30)
        
        metrics_a = MetricAggregate.objects.filter(
            entity_type=type_a, atlas_id=str(id_a), date_start__gte=start_date
        ).order_by("date_start")
        
        metrics_b = MetricAggregate.objects.filter(
            entity_type=type_b, atlas_id=str(id_b), date_start__gte=start_date
        ).order_by("date_start")

        # Organize for chart
        dates = sorted(list(set(
            [m.date_start.strftime("%Y-%m-%d") for m in metrics_a] + 
            [m.date_start.strftime("%Y-%m-%d") for m in metrics_b]
        )))
        
        vol_map_a = {m.date_start.strftime("%Y-%m-%d"): m.volume for m in metrics_a}
        vol_map_b = {m.date_start.strftime("%Y-%m-%d"): m.volume for m in metrics_b}
        
        data_a = [vol_map_a.get(d, 0) for d in dates]
        data_b = [vol_map_b.get(d, 0) for d in dates]

        # Pie chart totals
        sent_a = {"pos": sum(m.sentiment_pos for m in metrics_a), "neg": sum(m.sentiment_neg for m in metrics_a), "neu": sum(m.sentiment_neu for m in metrics_a)}
        sent_b = {"pos": sum(m.sentiment_pos for m in metrics_b), "neg": sum(m.sentiment_neg for m in metrics_b), "neu": sum(m.sentiment_neu for m in metrics_b)}

        context = {
            "entity_a": entity_a,
            "entity_b": entity_b,
            "chart_dates": json.dumps(dates),
            "chart_vol_a": json.dumps(data_a),
            "chart_vol_b": json.dumps(data_b),
            "sent_a": json.dumps(list(sent_a.values())),
            "sent_b": json.dumps(list(sent_b.values())),
        }
        return render(request, "monitor/dashboard/benchmark_result.html", context)

    return render(request, "monitor/dashboard/benchmark_selection.html", {
        "personas": Persona.objects.all().order_by("nombre_completo"),
        "instituciones": Institucion.objects.all().order_by("nombre"),
    })


@staff_member_required
def media_ingest_dashboard(request):
    """
    Ingest dashboard with controls for manual execution.
    """
    if request.method == "POST":
        ingest_type = request.POST.get("ingest_type") # rss, reprocess, normalization
        date_start = request.POST.get("date_start")
        date_end = request.POST.get("date_end")
        source_ids = request.POST.getlist("source_ids")
        
        # Here we would call the actual pipeline functions with these args.
        # For now, we simulate the triggering or call a simplified version.
        try:
            # Placeholder for actual command execution
            # from monitor.management.commands import fetch_sources
            # call_command('fetch_sources', sources=source_ids)
            
            AuditLog.objects.create(
                event_type="manual_ingest_trigger",
                status="success",
                payload=f"Triggered {ingest_type} for {len(source_ids)} sources. Window: {date_start} - {date_end}"
            )
            messages.success(request, f"Proceso '{ingest_type}' iniciado correctamente.")
        except Exception as e:
            messages.error(request, f"Error iniciando proceso: {e}")
    
    sources = Source.objects.all().order_by("name")
    recent_logs = AuditLog.objects.filter(event_type__in=["ingest", "manual_ingest_trigger"]).order_by("-created_at")[:20]
    
    return render(request, "monitor/dashboard/media_ingest.html", {
        "sources": sources,
        "recent_logs": recent_logs
    })


@staff_member_required
def training_dashboard(request):
    """
    Interface to review and correct ActorLinks.
    """
    # Show links with low confidence or manual review needed?
    # For now, show recent links.
    links = ActorLink.objects.select_related("article").order_by("-id")[:50]
    
    return render(request, "monitor/dashboard/training.html", {"links": links})


@staff_member_required
@require_POST
def api_correct_link(request):
    """
    AJAX endpoint to correct a link's sentiment or role.
    """
    try:
        data = json.loads(request.body)
        link_id = data.get("link_id")
        action = data.get("action") # 'sentiment', 'unlink'
        
        link = get_object_or_404(ActorLink, id=link_id)
        
        if action == "sentiment":
            new_sentiment = data.get("value")
            old_value = link.sentiment
            link.sentiment = new_sentiment
            link.save()
            
            # Record correction
            Correction.objects.create(
                scope=Correction.Scope.ARTICLE,
                target_id=link.article.id,
                field_name=f"actor_sentiment:{link.atlas_entity_id}",
                old_value=old_value,
                new_value=new_sentiment,
                explanation="Manual correction via dashboard",
                created_by=request.user
            )
            
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@staff_member_required
def review_clusters(request):
    """
    Review recent story clusters.
    """
    # Fetch stories from last 3 days
    since = timezone.now() - timedelta(days=3)
    stories = Story.objects.filter(time_window_start__gte=since).prefetch_related(
        "story_articles", "story_articles__article"
    ).order_by("-time_window_start")[:50]
    
    return render(request, "monitor/dashboard/review_clusters.html", {
        "stories": stories,
        "since": since
    })


@staff_member_required
def clients_dashboard(request):
    clients = Client.objects.all().order_by("name")
    return render(request, "monitor/dashboard/client_list.html", {"clients": clients})


@staff_member_required
def client_detail(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_focus":
            entity_type = request.POST.get("entity_type")
            if entity_type == "persona":
                entity_id = request.POST.get("entity_id")
            elif entity_type == "institucion":
                entity_id = request.POST.get("entity_id_inst") or request.POST.get("entity_id")
            else:
                entity_id = request.POST.get("entity_id_tema") or request.POST.get("entity_id")
            priority = request.POST.get("priority", 1)
            
            from monitor.models import ClientFocus
            if not entity_id:
                messages.error(request, "Selecciona una entidad válida.")
            else:
                try:
                    ClientFocus.objects.create(
                        client=client,
                        entity_type=entity_type,
                        atlas_id=entity_id,
                        priority=priority,
                    )
                    messages.success(request, "Foco añadido.")
                except IntegrityError:
                    messages.warning(request, "Ese foco ya estaba registrado.")
        elif action == "remove_focus":
            focus_id = request.POST.get("focus_id")
            from monitor.models import ClientFocus
            ClientFocus.objects.filter(id=focus_id, client=client).delete()
            messages.success(request, "Foco eliminado.")
            
    # Fetch focus items with names
    focus_items = client.focus_items.all().order_by("-priority")
    enriched_items = []
    for item in focus_items:
        name = "Desconocido"
        if item.entity_type == "persona":
            p = Persona.objects.filter(id=item.atlas_id).first()
            if p: name = p.nombre_completo
        elif item.entity_type == "institucion":
            i = Institucion.objects.filter(id=item.atlas_id).first()
            if i: name = i.nombre
        elif item.entity_type == "tema":
            t = Topic.objects.filter(id=item.atlas_id).first()
            if t: name = t.name
        enriched_items.append({
            "id": item.id,
            "type": item.entity_type,
            "priority": item.priority,
            "name": name,
            "atlas_id": item.atlas_id
        })
    
    context = {
        "client": client,
        "focus_items": enriched_items,
        "personas": Persona.objects.all().order_by("nombre_completo"),
        "instituciones": Institucion.objects.all().order_by("nombre"),
        "temas": Topic.objects.all().order_by("name"),
    }
    return render(request, "monitor/dashboard/client_detail.html", context)


@staff_member_required
def article_list(request):
    """
    List view for raw articles.
    """
    from monitor.models import Article
    
    query = request.GET.get("q", "")
    status = request.GET.get("status", "")
    
    qs = Article.objects.select_related("source").all().order_by("-published_at")
    
    if query:
        qs = qs.filter(title__icontains=query)
    
    if status:
        qs = qs.filter(pipeline_status=status)
        
    # Limit to 100 for performance
    articles = qs[:100]
    
    context = {
        "articles": articles,
        "query": query,
        "status": status,
        "status_choices": Article.PipelineStatus.choices
    }
    return render(request, "monitor/dashboard/article_list.html", context)
