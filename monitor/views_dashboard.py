from __future__ import annotations

import io
from typing import Dict

from django.contrib import messages
from django.core.management import call_command
from django.db import connections
from django.shortcuts import redirect, render
from django.utils import timezone

from monitor.models import Article, IngestRun, MediaOutlet, MediaSource, StoryCluster, StoryMention


def dashboard_home(request):
    counts = {
        "articles": Article.objects.count(),
        "sources": MediaSource.objects.count(),
        "outlets": MediaOutlet.objects.count(),
        "clusters": StoryCluster.objects.count(),
        "mentions": StoryMention.objects.count(),
    }
    last_run = IngestRun.objects.order_by("-started_at").first()
    return render(
        request,
        "monitor/dashboard/home.html",
        {
            "counts": counts,
            "last_run": last_run,
        },
    )


def _run_command(action: str) -> Dict[str, str]:
    buffer = io.StringIO()
    call_command(action, stdout=buffer)
    return {"stdout": buffer.getvalue()}


def media_ingest_dashboard(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action in {"fetch_sources", "cluster_articles_simple"}:
            try:
                _run_command(action)
                messages.success(request, f"Comando ejecutado: {action}")
            except Exception as exc:
                messages.error(request, f"Error ejecutando {action}: {exc}")
            return redirect("monitor_dashboard_ingest")

    last_fetch = IngestRun.objects.filter(action="fetch_sources").order_by("-started_at").first()
    last_cluster = IngestRun.objects.filter(action="cluster_articles_simple").order_by("-started_at").first()

    return render(
        request,
        "monitor/dashboard/media_ingest.html",
        {
            "last_fetch": last_fetch,
            "last_cluster": last_cluster,
        },
    )


def article_list(request):
    articles = Article.objects.select_related("outlet", "source").order_by("-published_at", "-id")[:100]
    return render(request, "monitor/dashboard/article_list.html", {"articles": articles})


def ops_dashboard(request):
    counts = {
        "articles": Article.objects.count(),
        "sources": MediaSource.objects.count(),
        "outlets": MediaOutlet.objects.count(),
        "clusters": StoryCluster.objects.count(),
        "mentions": StoryMention.objects.count(),
        "runs": IngestRun.objects.count(),
    }
    last_runs = IngestRun.objects.order_by("-started_at")[:10]
    sources_with_error = MediaSource.objects.exclude(last_error="").order_by("-last_fetched_at")[:10]
    recent_sources = MediaSource.objects.order_by("-last_fetched_at")[:10]

    db_ok = True
    try:
        connections["default"].cursor()
    except Exception:
        db_ok = False

    return render(
        request,
        "monitor/dashboard/ops.html",
        {
            "counts": counts,
            "db_ok": db_ok,
            "last_runs": last_runs,
            "sources_with_error": sources_with_error,
            "recent_sources": recent_sources,
            "now": timezone.now(),
        },
    )
