from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from redpolitica.models import Persona

from .forms_dashboard import OpsForm
from .models import (
    Article,
    ArticlePersonaMention,
    Digest,
    DigestClient,
    IngestRun,
    MediaOutlet,
    StoryCluster,
)


@staff_member_required
def dashboard_home(request):
    today = timezone.now().date()
    recent_runs = IngestRun.objects.order_by("-id")[:5]
    digest_latest = Digest.objects.order_by("-date", "-id").first()

    context = {
        "kpis": {
            "ingests_ok": IngestRun.objects.filter(status=IngestRun.Status.SUCCESS).count(),
            "articles_today": Article.objects.filter(published_at__date=today).count(),
            "clusters_today": StoryCluster.objects.filter(created_at__date=today).count(),
            "digests_total": Digest.objects.count(),
        },
        "recent_runs": recent_runs,
        "digest_latest": digest_latest,
    }
    return render(request, "monitor/dashboard/home.html", context)


@staff_member_required
def client_list(request):
    clients = DigestClient.objects.all().order_by("id")
    return render(request, "monitor/dashboard/client_list.html", {"clients": clients})


@staff_member_required
def client_create(request):
    # MVP: por ahora solo muestra pantalla (sin formulario real)
    messages.info(request, "client_create: pendiente de integrar formulario/modelo.")
    return redirect("monitor_dashboard_client_list")


@staff_member_required
def client_edit(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    return render(request, "monitor/dashboard/client_form.html", {"client": client})


@staff_member_required
def client_generate_digest(request, client_id: int):
    # MVP: comando existente en tu repo (lo vimos en management/commands)
    try:
        call_command("generate_client_digest", "--client-id", str(client_id))
        messages.success(request, "Digest generado.")
    except Exception as e:
        messages.error(request, f"Error generando digest: {e}")
    return redirect("monitor_dashboard_client_edit", client_id=client_id)

@staff_member_required
def digest_view(request, digest_id: int):
    return render(request, "monitor/dashboard/digest_view.html", {"digest": f"Digest ID: {digest_id}"})

@staff_member_required
def personas_list(request):
    query = request.GET.get("q", "").strip()
    personas = Persona.objects.all()
    if query:
        personas = personas.filter(nombre_completo__icontains=query)
    personas = personas.order_by("nombre_completo")[:200]

    return render(
        request,
        "monitor/dashboard/personas_list.html",
        {
            "personas": personas,
            "query": query,
        },
    )


def _persona_metrics(persona, days: int):
    since = timezone.now() - timedelta(days=days)
    mentions = ArticlePersonaMention.objects.filter(
        persona=persona,
        article__published_at__gte=since,
    ).select_related("article", "article__media_outlet")

    articles = Article.objects.filter(person_mentions__persona=persona, published_at__gte=since).distinct()
    sentiments = (
        Article.objects.filter(person_mentions__persona=persona, sentiment__isnull=False, published_at__gte=since)
        .values("sentiment__sentiment")
        .annotate(total=Count("id"))
    )
    sentiment_summary = {row["sentiment__sentiment"]: row["total"] for row in sentiments}

    outlets = (
        MediaOutlet.objects.filter(article__person_mentions__persona=persona, article__published_at__gte=since)
        .annotate(total=Count("article"))
        .order_by("-total")[:8]
    )

    top_clusters = (
        StoryCluster.objects.filter(mentions__article__person_mentions__persona=persona, created_at__gte=since)
        .annotate(total=Count("mentions"))
        .order_by("-total")[:6]
    )

    return {
        "mentions_count": mentions.count(),
        "articles_count": articles.count(),
        "outlets": outlets,
        "sentiment_summary": sentiment_summary,
        "clusters": top_clusters,
        "since": since,
    }


@staff_member_required
def persona_dashboard(request, persona_id: int):
    persona = get_object_or_404(Persona, id=persona_id)
    days = int(request.GET.get("days", 30))

    context = {
        "persona": persona,
        "days": days,
        "metrics": _persona_metrics(persona, days),
    }
    return render(request, "monitor/dashboard/persona_dashboard.html", context)


@staff_member_required
def benchmark_dashboard(request):
    persona_a = None
    persona_b = None
    days = int(request.GET.get("days", 30))

    persona_a_id = request.GET.get("a")
    persona_b_id = request.GET.get("b")

    if persona_a_id:
        persona_a = get_object_or_404(Persona, id=persona_a_id)
    if persona_b_id:
        persona_b = get_object_or_404(Persona, id=persona_b_id)

    metrics_a = _persona_metrics(persona_a, days) if persona_a else None
    metrics_b = _persona_metrics(persona_b, days) if persona_b else None

    top_outlets = []
    if persona_a and persona_b:
        since = timezone.now() - timedelta(days=days)
        outlets_a = MediaOutlet.objects.filter(
            article__person_mentions__persona=persona_a,
            article__published_at__gte=since,
        )
        outlets_b = MediaOutlet.objects.filter(
            article__person_mentions__persona=persona_b,
            article__published_at__gte=since,
        )
        outlet_counts = Counter(outlets_a.values_list("name", flat=True)) + Counter(
            outlets_b.values_list("name", flat=True)
        )
        top_outlets = outlet_counts.most_common(6)

    context = {
        "persona_a": persona_a,
        "persona_b": persona_b,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "days": days,
        "top_outlets": top_outlets,
        "personas": Persona.objects.order_by("nombre_completo")[:200],
    }
    return render(request, "monitor/dashboard/benchmark.html", context)


@staff_member_required
def ingest_dashboard(request):
    if request.method == "POST":
        form = OpsForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data.get("action")
            messages.info(request, "[DEBUG] action recibida = %s" % action)
            limit = int(form.cleaned_data.get("limit") or 200)

            try:
                if action == "fetch_sources":
                    call_command("fetch_sources", "--limit", str(limit))
                    messages.success(request, "fetch_sources OK")

                elif action == "fetch_article_bodies":
                    call_command("fetch_article_bodies", "--limit", str(limit))
                    messages.success(request, "fetch_article_bodies OK")

                elif action == "embed_articles":
                    call_command("embed_articles")
                    messages.success(request, "embed_articles OK")

                elif action == "cluster_articles_ai":
                    call_command("cluster_articles_ai")
                    messages.success(request, "cluster_articles_ai OK")

                else:
                    messages.error(request, f"Acción no reconocida: {action}")

            except Exception as e:
                messages.error(request, f"Error: {e}")

            return redirect("monitor_dashboard_ingest")
    else:
        form = OpsForm()

    context = {
        "form": form,
        "ingest_runs": IngestRun.objects.order_by("-id")[:10],
        "digests": Digest.objects.order_by("-date", "-id")[:10],
        "stats": {
            "ingest_total": IngestRun.objects.count(),
            "ingest_failed": IngestRun.objects.filter(status=IngestRun.Status.FAILED).count(),
            "articles_total": Article.objects.count(),
            "clusters_total": StoryCluster.objects.count(),
        },
    }

    return render(request, "monitor/dashboard/ingest.html", context)


@staff_member_required
def ops_run(request):
    return ingest_dashboard(request)
