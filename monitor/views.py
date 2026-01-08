import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.db.models import Q
from django.core.paginator import Paginator
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

import feedparser

from monitor.management.commands.fetch_sources import (
    crawl_sitemap,
    fetch_url_content,
)
from monitor.models import Article, Classification, EditorialReview, Mention, ProcessRun, Source
from weasyprint import HTML

from monitor.services import get_display_name, get_aliases
from redpolitica.models import Institucion, Persona, Topic

@ensure_csrf_cookie
def home(request):
    return render(request, "monitor/monitor-home.html", {"active_tab": "home"})


@ensure_csrf_cookie
def feed(request):
    return render(request, "monitor/monitor-feed.html", {"active_tab": "feed"})


@ensure_csrf_cookie
def dashboards(request):
    return render(request, "monitor/dashboards.html", {"active_tab": "dashboards"})


def dashboards_export(request):
    return _render_pdf(
        request,
        "monitor/dashboards-export.html",
        _dashboard_export_context(request),
        filename="dashboard.pdf",
    )


@ensure_csrf_cookie
def benchmarks(request):
    return render(request, "monitor/benchmarks.html", {"active_tab": "benchmarks"})


def benchmarks_export(request):
    return _render_pdf(
        request,
        "monitor/benchmarks-export.html",
        _benchmark_export_context(request),
        filename="benchmark.pdf",
    )


@ensure_csrf_cookie
def revision(request, article_id=None):
    return render(
        request,
        "monitor/revision.html",
        {"article_id": article_id, "active_tab": "revision"},
    )


@ensure_csrf_cookie
def procesos(request):
    return render(request, "monitor/procesos.html", {"active_tab": "procesos"})


@ensure_csrf_cookie
def sources(request):
    return render(request, "monitor/fuentes.html", {"active_tab": "sources"})


@ensure_csrf_cookie
def notes_list(request):
    return render(request, "monitor/notes_list.html", {"active_tab": "feed"})


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _format_datetime(value):
    if not value:
        return None
    localized = timezone.localtime(value)
    return localized.strftime("%d/%m/%Y %H:%M")


def _range_dates(range_key):
    today = timezone.now().date()
    if range_key == "year":
        return today.replace(month=1, day=1), today
    if range_key and range_key.isdigit():
        days = int(range_key)
        return today - timedelta(days=days), today
    return None, None


def _apply_date_filters(queryset, date_from, date_to):
    if date_from and date_to:
        return queryset.filter(
            Q(published_at__date__gte=date_from, published_at__date__lte=date_to)
            | Q(fetched_at__date__gte=date_from, fetched_at__date__lte=date_to)
        )
    if date_from:
        return queryset.filter(Q(published_at__date__gte=date_from) | Q(fetched_at__date__gte=date_from))
    if date_to:
        return queryset.filter(Q(published_at__date__lte=date_to) | Q(fetched_at__date__lte=date_to))
    return queryset


def _render_pdf(request, template_name, context, filename):
    html = render_to_string(template_name, context)
    base_url = request.build_absolute_uri("/")
    pdf = HTML(string=html, base_url=base_url).write_pdf()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _dashboard_export_context(request):
    queryset = Article.objects.select_related("source").order_by("-published_at", "-fetched_at")
    entity_type = request.GET.get("entity_type")
    entity_id = request.GET.get("entity_id")
    if entity_type and entity_id:
        queryset = queryset.filter(
            classification__mentions__target_type=entity_type,
            classification__mentions__target_id=entity_id,
        )
    article_type = request.GET.get("type")
    if article_type:
        queryset = queryset.filter(classification__article_type=article_type)

    sentiment = request.GET.get("sentiment")
    if sentiment:
        queryset = queryset.filter(classification__mentions__sentiment=sentiment)

    source_id = request.GET.get("source_id")
    if source_id:
        queryset = queryset.filter(source_id=source_id)
    range_key = request.GET.get("range")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if not (date_from or date_to) and range_key:
        date_from, date_to = _range_dates(range_key)
    if date_from or date_to:
        queryset = _apply_date_filters(queryset, date_from, date_to)

    data = _aggregate_dashboard(queryset)
    total_notes = len(data["scatter_points"])
    positive = data["sentiment_donut"].get("positivo", 0)
    opinion = data["type_donut"].get("opinion", 0)
    top_source = data["top_sources"][0]["source"] if data["top_sources"] else "—"
    return {
        "now": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "total_notes": total_notes,
        "positive_ratio": round((positive / total_notes) * 100, 1) if total_notes else 0,
        "opinion_ratio": round((opinion / total_notes) * 100, 1) if total_notes else 0,
        "top_source": top_source,
        "labels": [item["label"] for item in data["labels_cloud"][:10]],
        "timeline": data["timeline"],
        "sentiment_donut": data["sentiment_donut"],
        "type_donut": data["type_donut"],
    }


def _benchmark_export_context(request):
    a_type = request.GET.get("a_type")
    a_id = request.GET.get("a_id")
    b_type = request.GET.get("b_type")
    b_id = request.GET.get("b_id")

    base_queryset = Article.objects.select_related("source")
    range_key = request.GET.get("range")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if not (date_from or date_to) and range_key:
        date_from, date_to = _range_dates(range_key)
    if date_from or date_to:
        base_queryset = _apply_date_filters(base_queryset, date_from, date_to)

    a_queryset = base_queryset
    b_queryset = base_queryset
    if a_type and a_id:
        a_queryset = base_queryset.filter(
            classification__mentions__target_type=a_type,
            classification__mentions__target_id=a_id,
        )
    if b_type and b_id:
        b_queryset = base_queryset.filter(
            classification__mentions__target_type=b_type,
            classification__mentions__target_id=b_id,
        )
    a_data = _aggregate_dashboard(a_queryset)
    b_data = _aggregate_dashboard(b_queryset)

    def _resolve_name(entity_type, entity_id):
        if not (entity_type and entity_id):
            return "—"
        model = {"persona": Persona, "institucion": Institucion, "tema": Topic}.get(entity_type)
        if not model:
            return "—"
        try:
            return get_display_name(model.objects.get(id=entity_id))
        except model.DoesNotExist:
            return "—"

    return {
        "now": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "a_type": a_type,
        "a_id": a_id,
        "b_type": b_type,
        "b_id": b_id,
        "a_name": _resolve_name(a_type, a_id),
        "b_name": _resolve_name(b_type, b_id),
        "a_total": len(a_data["scatter_points"]),
        "b_total": len(b_data["scatter_points"]),
        "a_sentiment": a_data["sentiment_donut"],
        "b_sentiment": b_data["sentiment_donut"],
        "shared_labels": [
            label for label in {item["label"] for item in a_data["labels_cloud"]}
            if label in {item["label"] for item in b_data["labels_cloud"]}
        ],
        "a_labels": [item["label"] for item in a_data["labels_cloud"][:10]],
        "b_labels": [item["label"] for item in b_data["labels_cloud"][:10]],
        "timeline_a": a_data["timeline"],
        "timeline_b": b_data["timeline"],
    }


def _article_payload(article):
    classification = None
    try:
        classification = article.classification
    except ObjectDoesNotExist:
        classification = None
    mentions_payload = []
    if classification:
        for mention in classification.mentions.all():
            mentions_payload.append(
                {
                    "target_type": mention.target_type,
                    "target_id": mention.target_id,
                    "target_name": mention.target_name,
                    "sentiment": mention.sentiment,
                }
            )
    sentiment = "neutro"
    if classification and classification.mentions.exists():
        sentiment = classification.mentions.first().sentiment
    return {
        "id": article.id,
        "title": article.title,
        "source_name": article.source.name if article.source_id else "—",
        "published_at": (article.published_at or article.fetched_at).isoformat() if (article.published_at or article.fetched_at) else None,
        "published_at_display": _format_datetime(article.published_at or article.fetched_at),
        "url": article.url,
        "text_excerpt": (article.text or "")[:240],
        "article_type": classification.article_type if classification else None,
        "central_idea": classification.central_idea if classification else None,
        "labels": classification.labels_json if classification else [],
        "mentions": mentions_payload,
        "sentiment": sentiment,
        "status": article.status,
        "is_reviewed": bool(classification and classification.is_editor_locked),
    }


@require_GET
def api_summary(request):
    total_articles = Article.objects.count()
    pending_classification = Article.objects.filter(classification__isnull=True).count()
    pending_review = Classification.objects.filter(is_editor_locked=False).count()
    sources_error = Source.objects.filter(last_status="error").count()
    return JsonResponse(
        {
            "total_articles": total_articles,
            "pending_classification": pending_classification,
            "pending_review": pending_review,
            "sources_error": sources_error,
        }
    )


@require_GET
def api_entities(request):
    entity_type = request.GET.get("type")
    query = (request.GET.get("q") or "").strip()
    if entity_type not in {"persona", "institucion", "tema"}:
        return JsonResponse({"results": []})
    model = {"persona": Persona, "institucion": Institucion, "tema": Topic}[entity_type]
    queryset = model.objects.all()

    results = []
    query_lower = query.lower()
    for obj in queryset:
        name = get_display_name(obj)
        aliases = get_aliases(obj)
        haystack = " ".join([name] + aliases).lower()
        if query and query_lower not in haystack:
            continue
        results.append({"id": obj.id, "name": name, "type": entity_type})

    def score(item):
        if not query:
            return 0
        name = item["name"].lower()
        if name.startswith(query_lower):
            return 0
        if query_lower in name:
            return 1
        return 2

    results = sorted(results, key=score)[:20]
    return JsonResponse({"results": results})


@require_GET
def api_feed(request):
    queryset = (
        Article.objects.select_related("source", "classification")
        .prefetch_related("classification__mentions")
        .order_by("-published_at", "-fetched_at")
    )
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if date_from or date_to:
        queryset = _apply_date_filters(queryset, date_from, date_to)

    source_id = request.GET.get("source_id")
    if source_id:
        queryset = queryset.filter(source_id=source_id)

    query = request.GET.get("q")
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(text__icontains=query))

    article_type = request.GET.get("type")
    if article_type:
        queryset = queryset.filter(classification__article_type=article_type)

    sentiment = request.GET.get("sentiment")
    if sentiment:
        queryset = queryset.filter(classification__mentions__sentiment=sentiment)

    entity_type = request.GET.get("entity_type")
    entity_id = request.GET.get("entity_id")
    if entity_type and entity_id:
        queryset = queryset.filter(
            classification__mentions__target_type=entity_type,
            classification__mentions__target_id=entity_id,
        )
    label = request.GET.get("label")
    if label:
        queryset = queryset.filter(classification__labels_json__contains=[label])

    try:
        page_size = max(1, min(int(request.GET.get("page_size", 20)), 100))
    except (TypeError, ValueError):
        page_size = 20
    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1

    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)

    items = [_article_payload(article) for article in page_obj.object_list]
    return JsonResponse(
        {
            "items": items,
            "counts": {
                "total": paginator.count,
                "page": page_obj.number,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
            },
        }
    )


@require_GET
def api_article_detail(request, article_id):
    try:
        article = Article.objects.select_related("source").get(id=article_id)
    except Article.DoesNotExist as exc:
        return JsonResponse({"error": "Artículo no encontrado"}, status=404)
    payload = _article_payload(article)
    payload["reviews"] = [
        {
            "id": review.id,
            "created_at": _format_datetime(review.created_at),
            "created_by": review.created_by.get_username() if review.created_by_id else "—",
            "reason_text": review.reason_text,
        }
        for review in article.reviews.select_related("created_by").all()
    ]
    return JsonResponse(payload)


@require_GET
def api_review_navigation(request, article_id):
    try:
        current = Article.objects.annotate(
            sort_ts=Coalesce("published_at", "fetched_at")
        ).get(id=article_id)
    except Article.DoesNotExist as exc:
        return JsonResponse({"error": "Artículo no encontrado"}, status=404)

    pending_queryset = (
        Article.objects.filter(classification__is_editor_locked=False)
        .annotate(sort_ts=Coalesce("published_at", "fetched_at"))
        .order_by("-sort_ts", "-fetched_at", "-id")
    )

    prev_filter = (
        Q(sort_ts__gt=current.sort_ts)
        | Q(sort_ts=current.sort_ts, fetched_at__gt=current.fetched_at)
        | Q(
            sort_ts=current.sort_ts,
            fetched_at=current.fetched_at,
            id__gt=current.id,
        )
    )
    next_filter = (
        Q(sort_ts__lt=current.sort_ts)
        | Q(sort_ts=current.sort_ts, fetched_at__lt=current.fetched_at)
        | Q(
            sort_ts=current.sort_ts,
            fetched_at=current.fetched_at,
            id__lt=current.id,
        )
    )

    prev_article = pending_queryset.filter(prev_filter).order_by(
        "sort_ts", "fetched_at", "id"
    ).first()
    next_article = pending_queryset.filter(next_filter).order_by(
        "-sort_ts", "-fetched_at", "-id"
    ).first()

    return JsonResponse(
        {
            "prev_id": prev_article.id if prev_article else None,
            "next_id": next_article.id if next_article else None,
        }
    )


@require_POST
def api_article_review(request, article_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Autenticación requerida"}, status=401)
    try:
        article = Article.objects.select_related("source").get(id=article_id)
    except Article.DoesNotExist as exc:
        return JsonResponse({"error": "Artículo no encontrado"}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    reason_text = (payload.get("reason_text") or "").strip()
    if not reason_text:
        return JsonResponse({"error": "reason_text es obligatorio"}, status=400)

    try:
        classification = article.classification
    except ObjectDoesNotExist:
        classification = Classification.objects.create(
            article=article,
            central_idea=payload.get("central_idea", ""),
            article_type=payload.get("article_type", "informativo"),
            labels_json=payload.get("labels", []),
            model_name="editorial",
        )

    before_json = {
        "central_idea": classification.central_idea,
        "article_type": classification.article_type,
        "labels": classification.labels_json,
        "mentions": [
            {
                "target_type": mention.target_type,
                "target_id": mention.target_id,
                "target_name": mention.target_name,
                "sentiment": mention.sentiment,
            }
            for mention in classification.mentions.all()
        ],
    }

    classification.central_idea = payload.get("central_idea", classification.central_idea)
    classification.article_type = payload.get("article_type", classification.article_type)
    classification.labels_json = payload.get("labels", classification.labels_json)
    classification.is_editor_locked = True
    classification.save(update_fields=["central_idea", "article_type", "labels_json", "is_editor_locked"])

    mentions_payload = payload.get("mentions") or []
    classification.mentions.all().delete()
    Mention.objects.bulk_create(
        [
            Mention(
                classification=classification,
                target_type=item["target_type"],
                target_id=item["target_id"],
                target_name=item["target_name"],
                sentiment=item.get("sentiment", "neutro"),
                confidence=item.get("confidence", 0.5),
            )
            for item in mentions_payload
            if item.get("target_type") and item.get("target_id") and item.get("target_name")
        ]
    )

    after_json = {
        "central_idea": classification.central_idea,
        "article_type": classification.article_type,
        "labels": classification.labels_json,
        "mentions": [
            {
                "target_type": mention.target_type,
                "target_id": mention.target_id,
                "target_name": mention.target_name,
                "sentiment": mention.sentiment,
            }
            for mention in classification.mentions.all()
        ],
    }

    EditorialReview.objects.create(
        article=article,
        before_json=before_json,
        after_json=after_json,
        reason_text=reason_text,
        created_by=request.user,
    )

    return JsonResponse({"status": "ok"})


def _aggregate_dashboard(queryset):
    sentiment_counts = Counter()
    type_counts = Counter()
    label_counts = Counter()
    label_sentiments = defaultdict(Counter)
    scatter_points = []
    timeline_counts = defaultdict(lambda: {"total": 0, "positivo": 0, "neutro": 0, "negativo": 0})
    source_counts = Counter()

    for idx, article in enumerate(queryset):
        classification = None
        try:
            classification = article.classification
        except ObjectDoesNotExist:
            classification = None
        published = article.published_at or article.fetched_at
        if not published:
            continue
        sentiment = "neutro"
        if classification and classification.mentions.exists():
            sentiment = classification.mentions.first().sentiment
        scatter_points.append(
            {
                "x": published.isoformat(),
                "y": idx + 1,
                "sentiment": sentiment,
                "title": article.title,
                "url": article.url,
            }
        )
        source_counts[article.source.name if article.source_id else "—"] += 1

        if classification:
            type_counts[classification.article_type] += 1
            labels = classification.labels_json or []
            for label in labels:
                label_counts[label] += 1
                label_sentiments[label][sentiment] += 1
            for mention in classification.mentions.all():
                sentiment_counts[mention.sentiment] += 1
        else:
            sentiment_counts["neutro"] += 1

        period_key = published.date().isoformat()
        timeline_counts[period_key]["total"] += 1
        timeline_counts[period_key][sentiment] += 1

    labels_cloud = []
    for label, count in label_counts.most_common(30):
        dominant = "neutro"
        if label_sentiments[label]:
            dominant = label_sentiments[label].most_common(1)[0][0]
        labels_cloud.append({"label": label, "count": count, "dominant_sentiment": dominant})

    clusters = []
    for idx, (label, count) in enumerate(label_counts.most_common(5), start=1):
        clusters.append({"name": f"Historia {idx}", "labels": [label], "count": count})

    timeline = [
        {"period": period, **values}
        for period, values in sorted(timeline_counts.items())
    ]

    top_sources = [
        {"source": source, "count": count, "sentiment_balance": 0}
        for source, count in source_counts.most_common(10)
    ]

    return {
        "scatter_points": scatter_points,
        "sentiment_donut": {
            "positivo": sentiment_counts.get("positivo", 0),
            "neutro": sentiment_counts.get("neutro", 0),
            "negativo": sentiment_counts.get("negativo", 0),
        },
        "type_donut": {
            "informativo": type_counts.get("informativo", 0),
            "opinion": type_counts.get("opinion", 0),
        },
        "labels_cloud": labels_cloud,
        "clusters": clusters,
        "timeline": timeline,
        "top_sources": top_sources,
    }


@require_GET
def api_dashboard(request):
    queryset = Article.objects.select_related("source").order_by("-published_at", "-fetched_at")
    entity_type = request.GET.get("entity_type")
    entity_id = request.GET.get("entity_id")
    if entity_type and entity_id:
        queryset = queryset.filter(
            classification__mentions__target_type=entity_type,
            classification__mentions__target_id=entity_id,
        )

    article_type = request.GET.get("type")
    if article_type:
        queryset = queryset.filter(classification__article_type=article_type)

    sentiment = request.GET.get("sentiment")
    if sentiment:
        queryset = queryset.filter(classification__mentions__sentiment=sentiment)

    source_id = request.GET.get("source_id")
    if source_id:
        queryset = queryset.filter(source_id=source_id)

    range_key = request.GET.get("range")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if not (date_from or date_to) and range_key:
        date_from, date_to = _range_dates(range_key)
    if date_from or date_to:
        queryset = _apply_date_filters(queryset, date_from, date_to)

    return JsonResponse(_aggregate_dashboard(queryset))


@require_GET
def api_benchmark(request):
    a_type = request.GET.get("a_type")
    a_id = request.GET.get("a_id")
    b_type = request.GET.get("b_type")
    b_id = request.GET.get("b_id")

    if not (a_type and a_id and b_type and b_id):
        return JsonResponse({"error": "Parámetros incompletos"}, status=400)

    base_queryset = Article.objects.select_related("source")
    range_key = request.GET.get("range")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if not (date_from or date_to) and range_key:
        date_from, date_to = _range_dates(range_key)
    if date_from or date_to:
        base_queryset = _apply_date_filters(base_queryset, date_from, date_to)

    a_queryset = base_queryset.filter(
        classification__mentions__target_type=a_type,
        classification__mentions__target_id=a_id,
    )
    b_queryset = base_queryset.filter(
        classification__mentions__target_type=b_type,
        classification__mentions__target_id=b_id,
    )

    a_data = _aggregate_dashboard(a_queryset)
    b_data = _aggregate_dashboard(b_queryset)

    a_labels = {item["label"] for item in a_data["labels_cloud"]}
    b_labels = {item["label"] for item in b_data["labels_cloud"]}

    shared_labels = sorted(a_labels & b_labels)
    distinct_labels = {
        "a": sorted(a_labels - b_labels),
        "b": sorted(b_labels - a_labels),
    }

    return JsonResponse(
        {
            "a": a_data,
            "b": b_data,
            "shared_labels": shared_labels,
            "distinct_labels": distinct_labels,
            "tone_sources": {"a": a_data["top_sources"], "b": b_data["top_sources"]},
        }
    )


@require_GET
def api_sources(request):
    sources = Source.objects.all().order_by("name")
    return JsonResponse(
        {
            "items": [
                {
                    "id": source.id,
                    "name": source.name,
                    "type": source.source_type,
                    "url": source.url,
                    "is_active": source.is_active,
                    "frequency_minutes": source.frequency_minutes,
                    "last_status": source.last_status,
                    "last_run_at": source.last_run_at.isoformat() if source.last_run_at else None,
                    "last_error_text": source.last_error_text,
                    "last_new_count": source.last_new_count,
                }
                for source in sources
            ]
        }
    )


@require_POST
def api_sources_test(request, source_id):
    try:
        source = Source.objects.get(id=source_id)
    except Source.DoesNotExist as exc:
        return JsonResponse({"error": "Fuente no encontrada"}, status=404)

    preview = {"items_detected": 0, "has_text": False, "has_meta": False, "has_keywords": False}
    try:
        if source.source_type == "rss":
            parsed = feedparser.parse(source.url)  # type: ignore[name-defined]
            preview["items_detected"] = len(parsed.entries)
        elif source.source_type == "sitemap":
            urls = crawl_sitemap(source.url)
            preview["items_detected"] = len(urls)
            if urls:
                _, text, meta_desc, meta_keywords = fetch_url_content(urls[0])
                preview["has_text"] = bool(text)
                preview["has_meta"] = bool(meta_desc)
                preview["has_keywords"] = bool(meta_keywords)
        else:
            _, text, meta_desc, meta_keywords = fetch_url_content(source.url)
            preview["items_detected"] = 1
            preview["has_text"] = bool(text)
            preview["has_meta"] = bool(meta_desc)
            preview["has_keywords"] = bool(meta_keywords)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(preview)


@require_GET
def api_processes(request):
    runs = ProcessRun.objects.all().order_by("-started_at")[:10]
    return JsonResponse(
        {
            "automatic_mode": "manual",
            "items": [
                {
                    "id": run.id,
                    "run_type": run.run_type,
                    "status": run.status,
                    "date_from": run.date_from.isoformat() if run.date_from else None,
                    "date_to": run.date_to.isoformat() if run.date_to else None,
                    "started_at": run.started_at.isoformat(),
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "notes": run.notes,
                    "log_text": run.log_text,
                }
                for run in runs
            ]
        }
    )


@require_POST
def api_process_run(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    run_type = payload.get("run_type", "all")
    if run_type not in {"ingest", "classify", "all"}:
        return JsonResponse({"error": "run_type inválido"}, status=400)

    date_from = payload.get("date_from")
    date_to = payload.get("date_to")
    source_ids = payload.get("source_ids") or []
    notes = payload.get("notes", "")
    respect_editorial = payload.get("respect_editorial", True)
    force_classify = payload.get("force_classify", False)

    run = ProcessRun.objects.create(
        run_type=run_type,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        status="running",
        notes=notes,
    )

    log_buffer = io.StringIO()
    try:
        if run_type in {"ingest", "all"}:
            if source_ids:
                for source_id in source_ids:
                    call_command(
                        "fetch_sources",
                        stdout=log_buffer,
                        stderr=log_buffer,
                        source_id=source_id,
                    )
            else:
                call_command("fetch_sources", stdout=log_buffer, stderr=log_buffer)
        if run_type in {"classify", "all"}:
            classify_kwargs = {"stdout": log_buffer, "stderr": log_buffer}
            if date_from:
                classify_kwargs["date_from"] = date_from
            if date_to:
                classify_kwargs["date_to"] = date_to
            if not respect_editorial:
                classify_kwargs["ignore_editor_lock"] = True
            if force_classify:
                classify_kwargs["force"] = True
            call_command("classify_articles", **classify_kwargs)
        run.status = "ok"
    except Exception as exc:  # noqa: BLE001
        log_buffer.write(f"\nError: {exc}\n")
        run.status = "error"
    finally:
        run.finished_at = timezone.now()
        run.log_text = log_buffer.getvalue()
        run.save(update_fields=["status", "finished_at", "log_text"])

    return JsonResponse({"ok": run.status == "ok", "run_id": run.id, "log": run.log_text})


@require_POST
def api_export_dashboard(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}
    params = []
    for key in ("entity_type", "entity_id", "range", "grain", "source_id", "type", "sentiment"):
        if payload.get(key):
            params.append(f"{key}={payload[key]}")
    url = "/monitor/dashboards/export/"
    if params:
        url = f"{url}?{'&'.join(params)}"
    return JsonResponse({"url": url})


@require_POST
def api_export_benchmark(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = {}
    params = []
    for key in ("a_type", "a_id", "b_type", "b_id", "range", "grain"):
        if payload.get(key):
            params.append(f"{key}={payload[key]}")
    url = "/monitor/benchmarks/export/"
    if params:
        url = f"{url}?{'&'.join(params)}"
    return JsonResponse({"url": url})
