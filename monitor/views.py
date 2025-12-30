from __future__ import annotations

from typing import Iterable

from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from monitor.models import Article, Correction, MetricAggregate, Story
from monitor.pipeline import build_daily_digest, classify_articles, cluster_stories, ingest_sources


def monitor_health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "service": "monitor"})


def dashboard_home(request: HttpRequest) -> HttpResponse:
    return render(request, "monitor/dashboard.html", {"aggregates": MetricAggregate.objects.order_by("-date_start")[:50]})


def ingest_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    queryset = Article.objects.all()
    if status:
        queryset = queryset.filter(pipeline_status=status)
    articles = queryset.order_by("-published_at")[:200]
    return render(request, "monitor/ingest.html", {"articles": articles, "status": status})


@require_http_methods(["GET", "POST"])
def article_correction(request: HttpRequest, article_id: int) -> HttpResponse:
    article = get_object_or_404(Article, pk=article_id)
    if request.method == "POST":
        field_name = request.POST.get("field_name", "")
        new_value = request.POST.get("new_value", "")
        explanation = request.POST.get("explanation", "")
        Correction.objects.create(
            scope=Correction.Scope.ARTICLE,
            target_id=article.id,
            field_name=field_name,
            old_value="",
            new_value=new_value,
            explanation=explanation,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return redirect(reverse("monitor_article_correction", args=[article.id]))
    return render(
        request,
        "monitor/article_correction.html",
        {
            "article": article,
            "topic_links": article.topic_links.all(),
            "actor_links": article.actor_links.all(),
            "corrections": Correction.objects.filter(scope=Correction.Scope.ARTICLE, target_id=article.id),
        },
    )


@require_http_methods(["GET", "POST"])
def story_correction(request: HttpRequest, story_id: int) -> HttpResponse:
    story = get_object_or_404(Story, pk=story_id)
    if request.method == "POST":
        field_name = request.POST.get("field_name", "title_base")
        new_value = request.POST.get("new_value", "")
        explanation = request.POST.get("explanation", "")
        Correction.objects.create(
            scope=Correction.Scope.STORY,
            target_id=story.id,
            field_name=field_name,
            old_value=getattr(story, field_name, ""),
            new_value=new_value,
            explanation=explanation,
            created_by=request.user if request.user.is_authenticated else None,
        )
        setattr(story, field_name, new_value)
        story.save(update_fields=[field_name])
        return redirect(reverse("monitor_story_correction", args=[story.id]))
    return render(
        request,
        "monitor/story_correction.html",
        {
            "story": story,
            "articles": story.story_articles.select_related("article"),
            "corrections": Correction.objects.filter(scope=Correction.Scope.STORY, target_id=story.id),
        },
    )


def dashboard_view(request: HttpRequest) -> HttpResponse:
    aggregates = MetricAggregate.objects.order_by("-date_start")[:200]
    return render(request, "monitor/dashboard.html", {"aggregates": aggregates})


def dashboard_entity_view(request: HttpRequest, entity_type: str, atlas_id: str) -> HttpResponse:
    aggregates = MetricAggregate.objects.filter(entity_type=entity_type, atlas_id=atlas_id).order_by("-date_start")
    return render(request, "monitor/dashboard.html", {"aggregates": aggregates})


def _with_negative_percent(aggregates: Iterable[MetricAggregate]) -> list[MetricAggregate]:
    enriched = []
    for aggregate in aggregates:
        if aggregate.volume:
            aggregate.neg_percent = round((aggregate.sentiment_neg / aggregate.volume) * 100, 2)
        else:
            aggregate.neg_percent = 0
        enriched.append(aggregate)
    return enriched


def benchmarks_view(request: HttpRequest) -> HttpResponse:
    aggregates = MetricAggregate.objects.order_by("-date_start")[:200]
    return render(request, "monitor/benchmarks.html", {"aggregates": _with_negative_percent(aggregates)})


def export_pdf_placeholder(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "pending", "detail": "Exportación PDF en preparación."})


def placeholder_view(request: HttpRequest, title: str, message: str) -> HttpResponse:
    return render(request, "monitor/placeholder.html", {"title": title, "message": message})


def personas_placeholder(request: HttpRequest) -> HttpResponse:
    return placeholder_view(request, "Personas", "Dashboard por persona")


def instituciones_placeholder(request: HttpRequest) -> HttpResponse:
    return placeholder_view(request, "Instituciones", "Dashboard por institución")


def clients_placeholder(request: HttpRequest) -> HttpResponse:
    return placeholder_view(request, "Clientes", "Configuración de clientes")


def training_placeholder(request: HttpRequest) -> HttpResponse:
    return placeholder_view(request, "Entrenamiento", "Correcciones supervisadas")


def ops_placeholder(request: HttpRequest) -> HttpResponse:
    return placeholder_view(request, "Ops", "Operación del pipeline")


@require_http_methods(["POST"])
def api_job_ingest(request: HttpRequest) -> JsonResponse:
    articles = ingest_sources()
    return JsonResponse({"created": len(articles)})


@require_http_methods(["POST"])
def api_job_analyze(request: HttpRequest) -> JsonResponse:
    articles = list(Article.objects.order_by("-published_at")[:50])
    classify_articles(articles)
    return JsonResponse({"processed": len(articles)})


@require_http_methods(["POST"])
def api_job_cluster(request: HttpRequest) -> JsonResponse:
    stories = cluster_stories()
    return JsonResponse({"stories": stories})


@require_http_methods(["POST"])
def api_job_digest(request: HttpRequest) -> JsonResponse:
    items = build_daily_digest()
    return JsonResponse({"items": items})
