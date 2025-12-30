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

from monitor.ai import AIClient
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
    StoryMention,
    StoryCluster,
    TopicLink,
)

LOGGER = logging.getLogger(__name__)
USER_AGENT = "Mozilla/5.0 (MonitorHorizonte)"

# Initialize AI Client
ai_client = AIClient()

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
            try:
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
            except Exception as e:
                LOGGER.warning(f"Error parsing sitemap {sitemap_url}: {e}")
                continue

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
    
    LOGGER.info(f"Starting ingest for {len(sources)} sources.")

    for source in sources:
        last_error = ""
        source_stats = {"created": 0, "seen": 0, "skipped": 0, "errors": 0}
        try:
            per_source_limit = source.config.get("entry_limit") or limit
            entries = _fetch_entries_for_source(source, limit=per_source_limit)
            
            if not entries:
                source_stats["skipped"] = 0 # Just to log that we tried
            
            for entry in entries:
                try:
                    stats["seen"] += 1
                    source_stats["seen"] += 1
                    payload = dict(entry)
                    
                    # Fetch body if missing
                    raw_html = payload.get("raw_html") or ""
                    if not payload.get("body") and not raw_html:
                        try:
                            # Use requests directly to respect timeouts/headers
                            resp = requests.get(payload["url"], timeout=15, headers={"User-Agent": USER_AGENT})
                            if resp.status_code == 200:
                                raw_html = resp.text
                                payload["raw_html"] = raw_html
                        except Exception as e:
                            # If fetch fails, we might still store title/lead
                            LOGGER.warning(f"Could not fetch body for {payload['url']}: {e}")

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
            
            # Log source result
            LOGGER.info(f"Source {source.name}: {source_stats}")

        except Exception as exc:
            source.last_fetched_at = now
            source.last_error = str(exc)
            source.save(update_fields=["last_fetched_at", "last_error"])
            stats["errors"] += 1
            LOGGER.error(f"Source error {source.name}: {exc}")
            log_event("ingest_source", "error", {"error": str(exc)}, "source", str(source.id))

    status = "success" if stats["errors"] == 0 else "partial"
    log_event("ingest", status, stats)
    return IngestResult(created, stats)


def normalize_articles(articles: list[Article]) -> int:
    updated = 0
    for article in articles:
        cleaned_body = strip_tags(article.raw_html or article.body)
        if cleaned_body and cleaned_body != article.body:
            # Check for versioning
            ArticleVersion.objects.create(
                article=article,
                version=article.versions.count() + 1,
                title=article.title,
                lead=article.lead,
                body=cleaned_body,
            )
            article.body = cleaned_body
        
        # Here we would generate embedding if using Vector DB
        # embedding = ai_client.get_embedding(...)
        
        article.pipeline_status = Article.PipelineStatus.NORMALIZED
        article.save(update_fields=["body", "pipeline_status"])
        updated += 1
    log_event("normalize", "success", {"updated": updated})
    return updated


def classify_articles(articles: list[Article]) -> int:
    """
    Uses AI to classify articles and identify actor sentiment.
    """
    processed = 0
    for article in articles:
        # Pre-fetch existing names if any (e.g. from regex)
        # This helps AI focus its sentiment analysis
        existing_names = [al.atlas_entity_id for al in article.actor_links.all()] 
        # Note: atlas_entity_id is an ID, not a name. 
        # Ideally we pass names. We leave this empty for now or fetch names if vital.
        
        ai_result = ai_client.classify_article(
            title=article.title,
            body=article.body,
            entity_names=[] 
        )

        run = ClassificationRun.objects.create(
            article=article,
            model_name="gpt-4o-mini",
            model_version="v1",
            prompt_version="monitor-ai-v1",
            status=ClassificationRun.Status.SUCCESS,
            finished_at=timezone.now(),
        )
        
        content_type = ai_result.get("content_type", "informativo")
        scope = ai_result.get("scope", "estatal")
        
        Extraction.objects.create(
            classification_run=run,
            content_type=content_type,
            scope=scope,
            institutional_type=ai_result.get("institutional_type", "general"),
            notes=(ai_result.get("summary") or "")[:2000],
            raw_payload=ai_result,
        )

        # Trace
        DecisionTrace.objects.create(
            classification_run=run,
            field_name="content_type",
            value=content_type,
            confidence=0.8,
            rationale="AI Classification",
        )

        # Save Topics (Simple String match or Create)
        for topic_name in ai_result.get("topics", []):
            t_slug = clean_text(topic_name).upper().replace(" ", "_")[:50]
            TopicLink.objects.get_or_create(
                article=article,
                atlas_topic_id=t_slug,
                defaults={"confidence": 0.7, "rationale": "AI Topic"}
            )
            
        # Update Sentiment for Actors if AI returned it
        # (Requires matching names to ActorLinks, complex without fuzzy search)
        # We skip this detail update for now to avoid errors, relying on Regex defaults.
        # Future: Use AI to extract names AND sentiment, then link.

        article.pipeline_status = Article.PipelineStatus.CLASSIFIED
        article.save(update_fields=["pipeline_status"])
        processed += 1
        
    log_event("classify", "success", {"processed": processed})
    return processed


def link_articles(articles: list[Article]) -> int:
    # Uses User's fixed linking logic
    from monitor.linking import link_content, load_alias_map, load_topic_map

    links_created = 0
    alias_map, alias_regex = load_alias_map()
    topic_map, topic_regex = load_topic_map()
    
    for article in articles:
        links_created += link_content(article, alias_map, alias_regex, topic_map, topic_regex)

    log_event("link", "success", {"links_created": links_created})
    return links_created


def cluster_stories(hours: int = 24) -> int:
    """
    Intelligent clustering using Topic + Date buckets.
    (Embedding similarity can be added here once vector field exists)
    """
    since = timezone.now() - timedelta(hours=hours)
    articles = Article.objects.filter(published_at__gte=since).prefetch_related("topic_links")
    
    bucket = defaultdict(list)
    for article in articles:
        topic = article.topic_links.first()
        t_id = topic.atlas_topic_id if topic else "GENERAL"
        # Cluster by Day to avoid massive stories across weeks
        date_key = article.published_at.date() if article.published_at else timezone.now().date()
        
        bucket[(t_id, date_key)].append(article)

    created = 0
    for (topic_id, date_key), items in bucket.items():
        # Create a story for this Topic+Day
        # In a real vector system, we would sub-cluster `items` by similarity.
        
        window_start = timezone.make_aware(datetime.combine(date_key, time.min))
        window_end = window_start + timedelta(days=1)
        
        # Use first article as base title
        base_art = items[0]
        
        story, _ = Story.objects.get_or_create(
            main_topic_id=topic_id,
            time_window_start=window_start,
            time_window_end=window_end,
            defaults={
                "title_base": base_art.title,
                "lead_base": base_art.lead,
            },
        )
        
        for article in items:
            # Add to story
            StoryArticle.objects.get_or_create(
                story=story,
                article=article,
                defaults={"is_representative": article == base_art, "confidence": 0.6},
            )
            article.pipeline_status = Article.PipelineStatus.CLUSTERED
            article.save(update_fields=["pipeline_status"])
            
        created += 1
        
    log_event("cluster", "success", {"stories": created})
    return created


def aggregate_metrics(period: str = "day") -> int:
    # Full aggregation for recent data
    today = timezone.now().date()
    start = today
    end = today
    
    totals = defaultdict(lambda: {"volume": 0, "pos": 0, "neu": 0, "neg": 0})
    
    # Scan recent links (last 48h to catch late arrivals)
    since = timezone.now() - timedelta(days=2)
    links = ActorLink.objects.filter(article__published_at__gte=since).select_related("article")
    
    for link in links:
        d = link.article.published_at.date() if link.article.published_at else today
        key = (link.atlas_entity_type, link.atlas_entity_id, d)
        
        totals[key]["volume"] += 1
        s_key = "pos" if link.sentiment == ActorLink.Sentiment.POSITIVO else "neu" if link.sentiment == ActorLink.Sentiment.NEUTRO else "neg"
        totals[key][s_key] += 1

    updated = 0
    for (entity_type, atlas_id, date_val), values in totals.items():
        MetricAggregate.objects.update_or_create(
            entity_type=entity_type,
            atlas_id=atlas_id,
            period="day",
            date_start=date_val,
            date_end=date_val,
            defaults={
                "volume": values["volume"],
                "sentiment_pos": values["pos"],
                "sentiment_neu": values["neu"],
                "sentiment_neg": values["neg"],
            },
        )
        updated += 1
    log_event("aggregate", "success", {"aggregates": updated})
    return updated


def build_daily_digest(date: timezone.datetime.date | None = None) -> int:
    run_date = date or timezone.now().date()
    created = 0
    clients = Client.objects.filter(is_active=True).prefetch_related("focus_items")
    
    stories = Story.objects.filter(time_window_start__date=run_date)
    
    for client in clients:
        execution, _ = DailyExecution.objects.get_or_create(
            client=client,
            date=run_date,
            defaults={"status": DailyExecution.Status.RUNNING},
        )
        
        # Priority Map: {(type, id): priority_val}
        focus_map = {(f.entity_type, f.atlas_id): f.priority for f in client.focus_items.all()}
        
        for story in stories:
            # Check if story includes any relevant entity
            # This is an expensive check, optimizing by pre-fetching Story -> Article -> ActorLinks would be better.
            # For now, we query.
            story_links = ActorLink.objects.filter(article__story_articles__story=story)
            
            best_priority = 99 # Low priority default
            
            for link in story_links:
                k = (link.atlas_entity_type, link.atlas_entity_id)
                if k in focus_map:
                    p = focus_map[k]
                    if p < best_priority:
                        best_priority = p
            
            # Formatting section based on priority
            if best_priority <= 2:
                section = "Prioridad Alta"
            elif best_priority <= 5:
                section = "Seguimiento"
            else:
                section = "General"

            DailyDigestItem.objects.get_or_create(
                daily_execution=execution,
                story=story,
                defaults={
                    "section": section,
                    "rank_score": float(10 - best_priority), # higher is better
                    "display_title": story.title_base,
                    "display_lead": story.lead_base,
                    "outlets_chips": list(story.story_articles.values_list("article__outlet", flat=True)[:5]),
                },
            )
            created += 1
            
        execution.status = DailyExecution.Status.SUCCESS
        execution.save(update_fields=["status"])
        
    log_event("digest", "success", {"items": created})
    return created


@transaction.atomic
def run_pipeline(hours: int = 24, limit: int = 50) -> None:
    LOGGER.info("Starting pipeline run.")
    result = ingest_sources(limit=limit)
    if not result.articles:
        LOGGER.info("No new articles found.")
        
    normalize_articles(result.articles)
    
    # Classify (AI)
    classify_articles(result.articles)
    
    # Link (Regex - User defined)
    link_articles(result.articles)
    
    # Cluster (Topic+Date)
    cluster_stories(hours=hours)
    
    # Metrics
    aggregate_metrics()
    
    # Digest (Client Priority)
    build_daily_digest()
    
    LOGGER.info("Pipeline run complete.")
