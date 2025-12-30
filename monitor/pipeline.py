from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from monitor.models import (
    ActorLink,
    Article,
    ArticleVersion,
    AuditLog,
    ClassificationRun,
    Client,
    DailyDigestItem,
    DailyExecution,
    DecisionTrace,
    Extraction,
    MetricAggregate,
    Source,
    Story,
    StoryArticle,
    TopicLink,
)

LOGGER = logging.getLogger(__name__)


def log_event(event_type: str, status: str, payload: dict | None = None, entity_type: str = "", entity_id: str = "") -> None:
    AuditLog.objects.create(
        event_type=event_type,
        status=status,
        payload=payload or {},
        entity_type=entity_type,
        entity_id=entity_id,
    )
    LOGGER.info(json.dumps({"event": event_type, "status": status, "entity_type": entity_type, "entity_id": entity_id, **(payload or {})}))


def ingest_sources(limit: int = 50) -> list[Article]:
    now = timezone.now()
    created = []
    for source in Source.objects.filter(is_active=True)[:limit]:
        sample_url = f"{source.url.rstrip('/')}/sample-{int(now.timestamp())}.html"
        title = f"Nota de {source.outlet}"
        body = f"Contenido de prueba para {source.outlet}."
        hash_dedupe = Article.compute_hash(sample_url, sample_url, body)
        article, is_new = Article.objects.get_or_create(
            url=sample_url,
            defaults={
                "canonical_url": sample_url,
                "title": title,
                "lead": "",
                "body": body,
                "published_at": now,
                "fetched_at": now,
                "outlet": source.outlet,
                "language": "es",
                "hash_dedupe": hash_dedupe,
                "pipeline_status": Article.PipelineStatus.INGESTED,
                "source": source,
            },
        )
        if is_new:
            created.append(article)
    log_event("ingest", "success", {"created": len(created)})
    return created


def normalize_articles(articles: list[Article]) -> int:
    updated = 0
    for article in articles:
        cleaned_body = strip_tags(article.raw_html or article.body)
        if cleaned_body and cleaned_body != article.body:
            ArticleVersion.objects.create(
                article=article,
                version=article.versions.count() + 1,
                title=article.title,
                lead=article.lead,
                body=cleaned_body,
            )
            article.body = cleaned_body
        article.pipeline_status = Article.PipelineStatus.NORMALIZED
        article.save(update_fields=["body", "pipeline_status"])
        updated += 1
    log_event("normalize", "success", {"updated": updated})
    return updated


def classify_articles(articles: list[Article], model_name: str = "rule-based") -> int:
    processed = 0
    for article in articles:
        run = ClassificationRun.objects.create(
            article=article,
            model_name=model_name,
            model_version="v1",
            prompt_version="monitor-v1",
            status=ClassificationRun.Status.RUNNING,
        )
        content_type = Extraction.ContentType.INFORMATIVO
        scope = Extraction.Scope.ESTATAL
        Extraction.objects.create(
            classification_run=run,
            content_type=content_type,
            scope=scope,
            institutional_type="general",
            notes="clasificación inicial",
            raw_payload={
                "content_type": content_type,
                "scope": scope,
                "actors": [],
                "topics": [{"atlas_topic_id": "GENERAL", "confidence": 0.5, "rationale": "default"}],
                "tags": [],
                "notes": "clasificación base",
                "model_meta": {"model": model_name, "prompt_version": "monitor-v1"},
                "errors": [],
            },
        )
        DecisionTrace.objects.create(
            classification_run=run,
            field_name="content_type",
            value=content_type,
            confidence=0.6,
            rationale="default",
        )
        TopicLink.objects.get_or_create(
            article=article,
            atlas_topic_id="GENERAL",
            defaults={"confidence": 0.5, "rationale": "default"},
        )
        run.status = ClassificationRun.Status.SUCCESS
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        article.pipeline_status = Article.PipelineStatus.CLASSIFIED
        article.save(update_fields=["pipeline_status"])
        processed += 1
    log_event("classify", "success", {"processed": processed})
    return processed


def cluster_stories(hours: int = 24) -> int:
    since = timezone.now() - timedelta(hours=hours)
    articles = Article.objects.filter(published_at__gte=since)
    bucket = defaultdict(list)
    for article in articles:
        topic = article.topic_links.first()
        bucket_key = (topic.atlas_topic_id if topic else "GENERAL", article.published_at.date() if article.published_at else timezone.now().date())
        bucket[bucket_key].append(article)

    created = 0
    for (topic_id, date_key), items in bucket.items():
        window_start = timezone.make_aware(datetime.combine(date_key, time.min))
        window_end = window_start + timedelta(days=1)
        story, _ = Story.objects.get_or_create(
            main_topic_id=topic_id,
            time_window_start=window_start,
            time_window_end=window_end,
            defaults={
                "title_base": items[0].title,
                "lead_base": items[0].lead,
            },
        )
        for article in items:
            StoryArticle.objects.get_or_create(
                story=story,
                article=article,
                defaults={"is_representative": article == items[0], "confidence": 0.5},
            )
            article.pipeline_status = Article.PipelineStatus.CLUSTERED
            article.save(update_fields=["pipeline_status"])
        created += 1
    log_event("cluster", "success", {"stories": created})
    return created


def aggregate_metrics(period: str = "day") -> int:
    today = timezone.now().date()
    start = today
    end = today
    totals = defaultdict(lambda: {"volume": 0, "pos": 0, "neu": 0, "neg": 0, "opinion": 0, "informative": 0})
    for link in ActorLink.objects.select_related("article"):
        key = (link.atlas_entity_type, link.atlas_entity_id)
        totals[key]["volume"] += 1
        totals[key]["pos" if link.sentiment == ActorLink.Sentiment.POSITIVO else "neu" if link.sentiment == ActorLink.Sentiment.NEUTRO else "neg"] += 1
    for link in TopicLink.objects.select_related("article"):
        key = ("tema", link.atlas_topic_id)
        totals[key]["volume"] += 1
    updated = 0
    for (entity_type, atlas_id), values in totals.items():
        aggregate, _ = MetricAggregate.objects.update_or_create(
            entity_type=entity_type,
            atlas_id=atlas_id,
            period=period,
            date_start=start,
            date_end=end,
            defaults={
                "volume": values["volume"],
                "sentiment_pos": values["pos"],
                "sentiment_neu": values["neu"],
                "sentiment_neg": values["neg"],
                "share_opinion": 0.0,
                "share_informative": 0.0,
                "persistence_score": 0.0,
            },
        )
        updated += 1
    log_event("aggregate", "success", {"aggregates": updated})
    return updated


def build_daily_digest(date: timezone.datetime.date | None = None) -> int:
    run_date = date or timezone.now().date()
    created = 0
    for client in Client.objects.filter(is_active=True):
        execution, _ = DailyExecution.objects.get_or_create(
            client=client,
            date=run_date,
            defaults={"status": DailyExecution.Status.RUNNING},
        )
        stories = Story.objects.filter(time_window_start__date=run_date)
        for story in stories:
            DailyDigestItem.objects.get_or_create(
                daily_execution=execution,
                story=story,
                defaults={
                    "section": "federal",
                    "rank_score": 1.0,
                    "display_title": story.title_base,
                    "display_lead": story.lead_base,
                    "outlets_chips": list(story.story_articles.select_related("article").values_list("article__outlet", flat=True)),
                },
            )
            created += 1
        execution.status = DailyExecution.Status.SUCCESS
        execution.save(update_fields=["status"])
    log_event("digest", "success", {"items": created})
    return created


@transaction.atomic
def run_pipeline(hours: int = 24) -> None:
    articles = ingest_sources()
    normalize_articles(articles)
    classify_articles(articles)
    cluster_stories(hours=hours)
    aggregate_metrics()
    build_daily_digest()
