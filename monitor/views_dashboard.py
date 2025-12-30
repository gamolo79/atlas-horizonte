from collections import Counter, defaultdict
from datetime import timedelta
import json
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
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
                limit = int(request.POST.get("limit", 50))
                call_command("fetch_sources", limit=limit) # This assumes command name check
                # Actually pipeline.py logic is better invoked via management command wrapped nicely
                messages.success(request, "Ingest triggered.")
            elif action == "pipeline":
                # We should trigger the full pipeline
                from monitor.pipeline import run_pipeline
                run_pipeline(hours=24)
                messages.success(request, "Pipeline executed successfully.")
        except Exception as e:
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
