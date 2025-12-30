from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Iterable
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from readability import Document
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from monitor.management.commands.fetch_article_bodies import (
    clean_text,
    first_sentence,
    is_reliable_lead,
    normalize_body_html,
    strip_disclaimers,
)
from monitor.management.commands.fetch_sources import _clean_lead, _normalize_url, _safe_dt
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
USER_AGENT = "Mozilla/5.0 (MonitorHorizonte)"


@dataclass(frozen=True)
class IngestResult:
    articles: list[Article]
    stats: dict[str, int]


def _fetch_text(url: str) -> str:
    response = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def _canonical_from_html(html: str, fallback_url: str) -> str:
    if not html:
        return fallback_url
    soup = BeautifulSoup(html, "lxml")
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value.lower())
    if canonical_tag and canonical_tag.get("href"):
        return urljoin(fallback_url, canonical_tag["href"].strip())
    return fallback_url


def _extract_body(html: str) -> tuple[str, str]:
    if not html:
        return "", ""
    doc = Document(html)
    body_html = doc.summary()
    body_text = normalize_body_html(body_html)
    title = clean_text(doc.title() or "")
    return body_text, title


def _normalize_lead(lead: str, body_text: str) -> str:
    lead_text = clean_text(lead or "")
    if not is_reliable_lead(lead_text):
        lead_text = first_sentence(body_text)
    return strip_disclaimers(lead_text)[:2000]


def _extract_items_from_payload(payload: Any, items_path: str | None) -> list[dict]:
    data = payload
    if items_path:
        for chunk in items_path.split("."):
            if isinstance(data, dict):
                data = data.get(chunk, [])
            else:
                data = []
    elif isinstance(data, dict):
        data = data.get("items") or data.get("data") or []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _fetch_entries_for_source(source: Source, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if source.source_type == Source.SourceType.RSS:
        feed = feedparser.parse(source.url)
        for entry in feed.entries[:limit]:
            raw_url = (entry.get("link") or "").strip()
            url = _normalize_url(raw_url)
            if not url:
                continue
            published = None
            if entry.get("published"):
                published = _safe_dt(entry.get("published"))
            elif entry.get("updated"):
                published = _safe_dt(entry.get("updated"))
            entries.append(
                {
                    "url": url,
                    "title": (entry.get("title") or "").strip(),
                    "lead": _clean_lead(entry.get("summary") or ""),
                    "published_at": published,
                }
            )
    elif source.source_type == Source.SourceType.SITEMAP:
        sitemap_urls = source.config.get("sitemap_urls") or [source.url]
        for sitemap_url in sitemap_urls:
            xml = _fetch_text(sitemap_url)
            soup = BeautifulSoup(xml, "xml")
            sitemap_index = soup.find("sitemapindex")
            if sitemap_index:
                nested_urls = [loc.get_text(strip=True) for loc in sitemap_index.find_all("loc")]
                for nested_url in nested_urls:
                    xml = _fetch_text(nested_url)
                    soup = BeautifulSoup(xml, "xml")
                    entries.extend(_parse_sitemap_urls(soup, limit - len(entries)))
                    if len(entries) >= limit:
                        break
            else:
                entries.extend(_parse_sitemap_urls(soup, limit))
            if len(entries) >= limit:
                break
    elif source.source_type == Source.SourceType.HTML:
        list_url = source.config.get("list_url") or source.url
        link_selector = source.config.get("link_selector")
        link_attr = source.config.get("link_attr") or "href"
        if link_selector:
            html = _fetch_text(list_url)
            soup = BeautifulSoup(html, "lxml")
            for link in soup.select(link_selector):
                href = (link.get(link_attr) or "").strip()
                if not href:
                    continue
                url = _normalize_url(urljoin(list_url, href))
                entries.append({"url": url})
                if len(entries) >= limit:
                    break
        else:
            entries.append({"url": _normalize_url(list_url)})
    elif source.source_type == Source.SourceType.API:
        endpoint = source.config.get("endpoint") or source.url
        payload = requests.get(endpoint, timeout=25, headers={"User-Agent": USER_AGENT}).json()
        items = _extract_items_from_payload(payload, source.config.get("items_path"))
        url_field = source.config.get("url_field") or "url"
        title_field = source.config.get("title_field") or "title"
        lead_field = source.config.get("lead_field") or "lead"
        body_field = source.config.get("body_field") or "body"
        published_field = source.config.get("published_field") or "published_at"
        body_is_html = bool(source.config.get("body_is_html"))
        for item in items[:limit]:
            url = _normalize_url((item.get(url_field) or "").strip())
            if not url:
                continue
            published = _safe_dt(item.get(published_field))
            body_value = item.get(body_field) or ""
            raw_html = body_value if body_is_html and body_value else ""
            entries.append(
                {
                    "url": url,
                    "title": clean_text(item.get(title_field) or ""),
                    "lead": clean_text(item.get(lead_field) or ""),
                    "published_at": published,
                    "body": body_value if not body_is_html else "",
                    "raw_html": raw_html,
                    "body_is_html": body_is_html,
                }
            )
    return entries[:limit]


def _parse_sitemap_urls(soup: BeautifulSoup, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for url_tag in soup.find_all("url"):
        loc = url_tag.find("loc")
        if not loc or not loc.get_text(strip=True):
            continue
        url = _normalize_url(loc.get_text(strip=True))
        lastmod = url_tag.find("lastmod")
        published = _safe_dt(lastmod.get_text(strip=True)) if lastmod else None
        entries.append({"url": url, "published_at": published})
        if len(entries) >= limit:
            break
    return entries


def _store_article(
    source: Source,
    payload: dict[str, Any],
    now: timezone.datetime,
) -> tuple[Article | None, bool]:
    url = payload.get("url") or ""
    if not url:
        return None, False
    if Article.objects.filter(url=url).exists():
        return None, False

    raw_html = payload.get("raw_html") or ""
    body_text = payload.get("body") or ""
    title = clean_text(payload.get("title") or "")
    lead = payload.get("lead") or ""
    published_at = payload.get("published_at")

    if not raw_html and body_text:
        raw_html = body_text
    if payload.get("body_is_html") and raw_html:
        body_text = normalize_body_html(raw_html)
    if raw_html and not body_text:
        body_text, inferred_title = _extract_body(raw_html)
        if not title:
            title = inferred_title

    lead = _normalize_lead(lead, body_text)
    canonical_url = _canonical_from_html(raw_html, payload.get("canonical_url") or url)
    hash_dedupe = Article.compute_hash(url, canonical_url, body_text or "")
    if Article.objects.filter(hash_dedupe=hash_dedupe).exists():
        return None, False

    article = Article.objects.create(
        source=source,
        url=url,
        canonical_url=canonical_url,
        title=title or url,
        lead=lead,
        body=body_text or "",
        raw_html=raw_html or "",
        published_at=published_at,
        fetched_at=now,
        outlet=source.outlet,
        language="es",
        hash_dedupe=hash_dedupe,
        pipeline_status=Article.PipelineStatus.INGESTED,
    )
    return article, True


def log_event(event_type: str, status: str, payload: dict | None = None, entity_type: str = "", entity_id: str = "") -> None:
    AuditLog.objects.create(
        event_type=event_type,
        status=status,
        payload=payload or {},
        entity_type=entity_type,
        entity_id=entity_id,
    )
    LOGGER.info(json.dumps({"event": event_type, "status": status, "entity_type": entity_type, "entity_id": entity_id, **(payload or {})}))


def ingest_sources(limit: int = 50) -> IngestResult:
    now = timezone.now()
    created: list[Article] = []
    stats = {"created": 0, "seen": 0, "skipped": 0, "errors": 0}
    sources = Source.objects.filter(is_active=True)[:limit]
    for source in sources:
        last_error = ""
        source_stats = {"created": 0, "seen": 0, "skipped": 0, "errors": 0}
        try:
            per_source_limit = source.config.get("entry_limit") or limit
            entries = _fetch_entries_for_source(source, limit=per_source_limit)
            for entry in entries:
                try:
                    stats["seen"] += 1
                    source_stats["seen"] += 1
                    payload = dict(entry)
                    raw_html = payload.get("raw_html") or ""
                    if not payload.get("body") and not raw_html:
                        raw_html = _fetch_text(payload["url"])
                        payload["raw_html"] = raw_html
                    article, is_new = _store_article(source, payload, now)
                    if is_new and article:
                        created.append(article)
                        stats["created"] += 1
                        source_stats["created"] += 1
                    else:
                        stats["skipped"] += 1
                        source_stats["skipped"] += 1
                except Exception as exc:
                    last_error = str(exc)
                    stats["errors"] += 1
                    source_stats["errors"] += 1
                    log_event(
                        "ingest_article",
                        "error",
                        {"error": str(exc), "url": entry.get("url")},
                        "source",
                        str(source.id),
                    )
            source.last_fetched_at = now
            source.last_error = last_error
            source.save(update_fields=["last_fetched_at", "last_error"])
            source_status = "success" if not last_error else "partial"
            log_event(
                "ingest_source",
                source_status,
                source_stats,
                "source",
                str(source.id),
            )
        except Exception as exc:
            source.last_fetched_at = now
            source.last_error = str(exc)
            source.save(update_fields=["last_fetched_at", "last_error"])
            stats["errors"] += 1
            log_event("ingest_source", "error", {"error": str(exc)}, "source", str(source.id))

    status = "success" if stats["errors"] == 0 else "partial"
    log_event("ingest", status, stats)
    return IngestResult(created, stats)


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


    build_daily_digest()


def link_articles(articles: list[Article]) -> int:
    # Local import to avoid circular dependency
    from monitor.linking import link_content
    
    links_created = 0
    # Process all articles
    for article in articles:
        links_created += link_content(article)
    
    log_event("link", "success", {"links_created": links_created})
    return links_created


@transaction.atomic
def run_pipeline(hours: int = 24) -> None:
    result = ingest_sources()
    normalize_articles(result.articles)
    classify_articles(result.articles)
    link_articles(result.articles)
    cluster_stories(hours=hours)
    aggregate_metrics()
    build_daily_digest()
