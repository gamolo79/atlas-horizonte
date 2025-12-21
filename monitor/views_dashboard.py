from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.management import call_command
from django.db import OperationalError, ProgrammingError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from redpolitica.models import Institucion, Persona

from .aggregations import ensure_cluster_aggregates
from .forms_dashboard import DigestClientConfigForm, DigestClientForm, OpsForm
from .models import (
    Article,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    ArticleSentiment,
    Digest,
    DigestClient,
    DigestClientConfig,
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
    if request.method == "POST":
        form_client = DigestClientForm(request.POST)
        form_cfg = DigestClientConfigForm(request.POST)
        if form_client.is_valid() and form_cfg.is_valid():
            client = form_client.save()
            config = form_cfg.save(commit=False)
            config.client = client
            config.save()
            form_cfg.save_m2m()
            messages.success(request, "Cliente creado correctamente.")
            return redirect("monitor_dashboard_client_edit", client_id=client.id)
    else:
        form_client = DigestClientForm()
        form_cfg = DigestClientConfigForm()

    return render(
        request,
        "monitor/dashboard/client_form.html",
        {
            "form_client": form_client,
            "form_cfg": form_cfg,
            "is_edit": False,
        },
    )


@staff_member_required
def client_edit(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    config, _ = DigestClientConfig.objects.get_or_create(client=client)

    if request.method == "POST":
        form_client = DigestClientForm(request.POST, instance=client)
        form_cfg = DigestClientConfigForm(request.POST, instance=config)
        if form_client.is_valid() and form_cfg.is_valid():
            form_client.save()
            form_cfg.save()
            messages.success(request, "Cliente actualizado correctamente.")
            return redirect("monitor_dashboard_client_edit", client_id=client.id)
    else:
        form_client = DigestClientForm(instance=client)
        form_cfg = DigestClientConfigForm(instance=config)

    digests = Digest.objects.filter(title=config.title).order_by("-date", "-id")[:5]
    return render(
        request,
        "monitor/dashboard/client_form.html",
        {
            "client": client,
            "config": config,
            "form_client": form_client,
            "form_cfg": form_cfg,
            "digests": digests,
            "is_edit": True,
        },
    )


@staff_member_required
def client_delete(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    if request.method == "POST":
        client.delete()
        messages.success(request, "Cliente eliminado.")
        return redirect("monitor_dashboard_client_list")
    return render(request, "monitor/dashboard/client_delete.html", {"client": client})


@staff_member_required
def client_digest_history(request, client_id: int):
    client = get_object_or_404(DigestClient, id=client_id)
    config = getattr(client, "config", None)
    if config:
        digests = Digest.objects.filter(title=config.title).order_by("-date", "-id")
    else:
        digests = Digest.objects.none()
    return render(
        request,
        "monitor/dashboard/client_digest_history.html",
        {
            "client": client,
            "config": config,
            "digests": digests,
        },
    )


@staff_member_required
def client_generate_digest(request, client_id: int):
    # MVP: comando existente en tu repo (lo vimos en management/commands)
    client = get_object_or_404(DigestClient, id=client_id)
    try:
        try:
            config = client.config
        except DigestClientConfig.DoesNotExist:
            messages.error(request, "El cliente no tiene configuración de digest.")
            return redirect("monitor_dashboard_client_edit", client_id=client_id)

        person_ids = list(config.personas.values_list("id", flat=True))
        institution_ids = list(config.instituciones.values_list("id", flat=True))
        if not person_ids and not institution_ids:
            messages.error(request, "La configuración no tiene personas ni instituciones.")
            return redirect("monitor_dashboard_client_edit", client_id=client_id)

        cmd_args = [
            "--title", config.title,
            "--top", str(config.top_n),
            "--hours", str(config.hours),
        ]
        for pid in person_ids:
            cmd_args.extend(["--person-id", str(pid)])
        for iid in institution_ids:
            cmd_args.extend(["--institution-id", str(iid)])

        call_command("generate_client_digest", *cmd_args)
        messages.success(request, "Digest generado.")
    except Exception as e:
        messages.error(request, f"Error generando digest: {e}")
    return redirect("monitor_dashboard_client_edit", client_id=client_id)

@staff_member_required
def digest_view(request, digest_id: int):
    digest = get_object_or_404(Digest, id=digest_id)
    return render(request, "monitor/dashboard/digest_view.html", {"digest": digest})

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


@staff_member_required
def instituciones_list(request):
    query = request.GET.get("q", "").strip()
    instituciones = Institucion.objects.all()
    if query:
        instituciones = instituciones.filter(nombre__icontains=query)
    instituciones = instituciones.order_by("nombre")[:200]

    return render(
        request,
        "monitor/dashboard/instituciones_list.html",
        {
            "instituciones": instituciones,
            "query": query,
        },
    )


def _build_sentiment_summary(sentiment_rows):
    sentiment_summary = {choice.value: 0 for choice in ArticleSentiment.Sentiment}
    for row in sentiment_rows:
        sentiment_summary[row["sentiment"]] = row["total"]
    return sentiment_summary


def _persona_metrics(persona, days: int):
    since = timezone.now() - timedelta(days=days)
    mentions = ArticlePersonaMention.objects.filter(
        persona=persona,
        article__published_at__gte=since,
    ).select_related("article", "article__media_outlet")

    articles = Article.objects.filter(person_mentions__persona=persona, published_at__gte=since).distinct()
    try:
        sentiments = (
            ArticlePersonaMention.objects.filter(
                persona=persona,
                sentiment__isnull=False,
                article__published_at__gte=since,
            )
            .values("sentiment")
            .annotate(total=Count("id"))
        )
        sentiment_summary = _build_sentiment_summary(sentiments)
    except (OperationalError, ProgrammingError):
        sentiments = (
            Article.objects.filter(
                person_mentions__persona=persona,
                sentiment__isnull=False,
                published_at__gte=since,
            )
            .values("sentiment__sentiment")
            .annotate(total=Count("id"))
        )
        sentiment_summary = {
            row["sentiment__sentiment"]: row["total"] for row in sentiments
        }
        sentiment_summary = {
            choice.value: sentiment_summary.get(choice.value, 0)
            for choice in ArticleSentiment.Sentiment
        }
    sentiment_total = sum(sentiment_summary.values())

    outlets = (
        MediaOutlet.objects.filter(article__person_mentions__persona=persona, article__published_at__gte=since)
        .annotate(total=Count("article"))
        .order_by("-total")[:8]
    )

    # 2-step query to avoid duplicates from joins + distinct + annotate interaction
    matching_cluster_ids = (
        StoryCluster.objects.filter(
            mentions__article__person_mentions__persona=persona,
            created_at__gte=since,
        )
        .values_list("id", flat=True)
        .distinct()
    )

    top_clusters = (
        StoryCluster.objects.filter(id__in=matching_cluster_ids)
        .annotate(total=Count("mentions", distinct=True))
        .order_by("-total")[:6]
    )
    ensure_cluster_aggregates(top_clusters)

    topic_counter = Counter()
    for topics in articles.values_list("topics", flat=True):
        if not topics:
            continue
        for topic in topics:
            label = topic.get("label") if isinstance(topic, dict) else str(topic)
            if label:
                topic_counter[label] += 1
    topic_summary = [
        {"label": label, "total": total}
        for label, total in topic_counter.most_common(6)
    ]

    return {
        "mentions_count": mentions.count(),
        "articles_count": articles.count(),
        "outlets": outlets,
        "sentiment_summary": sentiment_summary,
        "sentiment_total": sentiment_total,
        "clusters": top_clusters,
        "topic_summary": topic_summary,
        "since": since,
    }


def _institucion_metrics(institucion, days: int):
    since = timezone.now() - timedelta(days=days)
    mentions = ArticleInstitucionMention.objects.filter(
        institucion=institucion,
        article__published_at__gte=since,
    ).select_related("article", "article__media_outlet")

    articles = Article.objects.filter(
        institution_mentions__institucion=institucion,
        published_at__gte=since,
    ).distinct()
    try:
        sentiments = (
            ArticleInstitucionMention.objects.filter(
                institucion=institucion,
                sentiment__isnull=False,
                article__published_at__gte=since,
            )
            .values("sentiment")
            .annotate(total=Count("id"))
        )
        sentiment_summary = _build_sentiment_summary(sentiments)
    except (OperationalError, ProgrammingError):
        sentiments = (
            Article.objects.filter(
                institution_mentions__institucion=institucion,
                sentiment__isnull=False,
                published_at__gte=since,
            )
            .values("sentiment__sentiment")
            .annotate(total=Count("id"))
        )
        sentiment_summary = {
            row["sentiment__sentiment"]: row["total"] for row in sentiments
        }
        sentiment_summary = {
            choice.value: sentiment_summary.get(choice.value, 0)
            for choice in ArticleSentiment.Sentiment
        }
    sentiment_total = sum(sentiment_summary.values())

    outlets = (
        MediaOutlet.objects.filter(
            article__institution_mentions__institucion=institucion,
            article__published_at__gte=since,
        )
        .annotate(total=Count("article"))
        .order_by("-total")[:8]
    )

    # 2-step query to avoid duplicates
    matching_cluster_ids = (
        StoryCluster.objects.filter(
            mentions__article__institution_mentions__institucion=institucion,
            created_at__gte=since,
        )
        .values_list("id", flat=True)
        .distinct()
    )

    top_clusters = (
        StoryCluster.objects.filter(id__in=matching_cluster_ids)
        .annotate(total=Count("mentions", distinct=True))
        .order_by("-total")[:6]
    )
    ensure_cluster_aggregates(top_clusters)

    topic_counter = Counter()
    for topics in articles.values_list("topics", flat=True):
        if not topics:
            continue
        for topic in topics:
            label = topic.get("label") if isinstance(topic, dict) else str(topic)
            if label:
                topic_counter[label] += 1
    topic_summary = [
        {"label": label, "total": total}
        for label, total in topic_counter.most_common(6)
    ]

    return {
        "mentions_count": mentions.count(),
        "articles_count": articles.count(),
        "outlets": outlets,
        "sentiment_summary": sentiment_summary,
        "sentiment_total": sentiment_total,
        "clusters": top_clusters,
        "topic_summary": topic_summary,
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
def institucion_dashboard(request, institucion_id: int):
    institucion = get_object_or_404(Institucion, id=institucion_id)
    days = int(request.GET.get("days", 30))

    context = {
        "institucion": institucion,
        "days": days,
        "metrics": _institucion_metrics(institucion, days),
    }
    return render(request, "monitor/dashboard/institucion_dashboard.html", context)


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
def institucion_benchmark_dashboard(request):
    institucion_a = None
    institucion_b = None
    days = int(request.GET.get("days", 30))

    institucion_a_id = request.GET.get("a")
    institucion_b_id = request.GET.get("b")

    if institucion_a_id:
        institucion_a = get_object_or_404(Institucion, id=institucion_a_id)
    if institucion_b_id:
        institucion_b = get_object_or_404(Institucion, id=institucion_b_id)

    metrics_a = _institucion_metrics(institucion_a, days) if institucion_a else None
    metrics_b = _institucion_metrics(institucion_b, days) if institucion_b else None

    top_outlets = []
    if institucion_a and institucion_b:
        since = timezone.now() - timedelta(days=days)
        outlets_a = MediaOutlet.objects.filter(
            article__institution_mentions__institucion=institucion_a,
            article__published_at__gte=since,
        )
        outlets_b = MediaOutlet.objects.filter(
            article__institution_mentions__institucion=institucion_b,
            article__published_at__gte=since,
        )
        outlet_counts = Counter(outlets_a.values_list("name", flat=True)) + Counter(
            outlets_b.values_list("name", flat=True)
        )
        top_outlets = outlet_counts.most_common(6)

    context = {
        "institucion_a": institucion_a,
        "institucion_b": institucion_b,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "days": days,
        "top_outlets": top_outlets,
        "instituciones": Institucion.objects.order_by("nombre")[:200],
    }
    return render(request, "monitor/dashboard/institucion_benchmark.html", context)


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
                    source_id = form.cleaned_data.get("source_id")
                    cmd_args = ["--limit", str(limit)]
                    if source_id:
                        cmd_args.extend(["--source-id", str(source_id)])
                    call_command("fetch_sources", *cmd_args)
                    messages.success(request, "fetch_sources OK")

                elif action == "fetch_article_bodies":
                    force = form.cleaned_data.get("force")
                    cmd_args = ["--limit", str(limit)]
                    if force:
                        cmd_args.append("--force")
                    call_command("fetch_article_bodies", *cmd_args)
                    messages.success(request, "fetch_article_bodies OK")

                elif action == "embed_articles":
                    call_command("embed_articles", "--limit", str(limit))
                    messages.success(request, "embed_articles OK")

                elif action == "cluster_articles_ai":
                    hours = form.cleaned_data.get("hours")
                    threshold = form.cleaned_data.get("threshold")
                    dry_run = form.cleaned_data.get("dry_run")
                    cmd_args = [
                        "--limit", str(limit),
                        "--hours", str(hours),
                        "--threshold", str(threshold),
                    ]
                    if dry_run:
                        cmd_args.append("--dry-run")
                    call_command("cluster_articles_ai", *cmd_args)
                    messages.success(request, "cluster_articles_ai OK")

                elif action == "link_entities":
                    hours = form.cleaned_data.get("hours")
                    call_command(
                        "link_entities",
                        "--limit",
                        str(limit),
                        "--since",
                        f"{hours}h",
                    )
                    messages.success(request, "link_entities OK")

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
