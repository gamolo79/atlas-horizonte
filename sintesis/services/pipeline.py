from __future__ import annotations

import hashlib
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Prefetch, Q
from django.db.models.fields.files import FieldFile
from django.template.loader import render_to_string
from django.utils import timezone

from atlas_core.text_utils import normalize_name
from monitor.models import Article
from monitor.services import parse_json_response
from sintesis.models import (
    SynthesisRun,
    SynthesisRunSection,
    SynthesisSectionRoutingResult,
    SynthesisSectionFilter,
    SynthesisSectionTemplate,
    SynthesisArticleMentionStrength,
    SynthesisArticleEmbedding,
    SynthesisArticleDedup,
    SynthesisCluster,
    SynthesisStory,
    SynthesisStoryArticle,
)
from sintesis.services import build_profile, group_profiles
from sintesis.services.clustering import assign_articles_to_clusters
from sintesis.services.llm_labels import label_clusters
from sintesis.services.embeddings import (
    build_canonical_text,
    canonical_hash,
    compute_embedding,
    update_embedding_vector,
)
from sintesis.services.mention_strength import classify_mentions


logger = logging.getLogger(__name__)


def build_run_window(
    schedule=None,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    if window_start and window_end:
        return window_start, window_end

    now = now or timezone.now()
    if schedule:
        tz = timezone.get_current_timezone()
        local_run = schedule.next_run_at or now
        local_date = timezone.localtime(local_run, tz=tz).date()
        window_start = timezone.make_aware(
            datetime.combine(local_date, schedule.window_start_time), tz
        )
        window_end = timezone.make_aware(
            datetime.combine(local_date, schedule.window_end_time), tz
        )
        if window_end <= window_start:
            window_end = window_end + timedelta(days=1)
        return window_start, window_end

    window_end = now
    window_start = now - timedelta(hours=12)
    return window_start, window_end


def _collect_keywords(filters: Iterable[SynthesisSectionFilter]) -> List[str]:
    keywords: List[str] = []
    for item in filters:
        if item.keywords_json:
            keywords.extend([str(word).strip() for word in item.keywords_json if word])
        if item.keywords:
            keywords.extend([word.strip() for word in item.keywords.split(",") if word.strip()])
    seen = set()
    variants: List[str] = []
    for keyword in keywords:
        for variant in {keyword, keyword.lower(), normalize_name(keyword)}:
            if not variant:
                continue
            if variant in seen:
                continue
            seen.add(variant)
            variants.append(variant)
    return variants


def fetch_candidate_articles(
    window: Tuple[datetime, datetime],
    section_filters: Iterable[SynthesisSectionFilter],
):
    window_start, window_end = window
    base_qs = (
        Article.objects.filter(status="processed")
        .select_related("source", "classification")
        .prefetch_related("classification__mentions")
        .order_by("-published_at", "-fetched_at")
    )
    if window_start and window_end:
        base_qs = base_qs.filter(
            Q(published_at__gte=window_start, published_at__lte=window_end)
            | Q(fetched_at__gte=window_start, fetched_at__lte=window_end)
        )

    filters = list(section_filters)
    if not filters:
        return base_qs

    q = Q()
    keywords = _collect_keywords(filters)
    for item in filters:
        if item.persona_id:
            q |= Q(
                classification__mentions__target_type="persona",
                classification__mentions__target_id=item.persona_id,
            )
        if item.institucion_id:
            q |= Q(
                classification__mentions__target_type="institucion",
                classification__mentions__target_id=item.institucion_id,
            )
        if item.topic_id:
            q |= Q(
                classification__mentions__target_type="tema",
                classification__mentions__target_id=item.topic_id,
            )

    for keyword in keywords:
        q |= Q(classification__labels_json__contains=[keyword])
        q |= Q(title__icontains=keyword) | Q(text__icontains=keyword)

    return base_qs.filter(q).distinct()


def _fetch_window_articles(window: Tuple[datetime, datetime]):
    window_start, window_end = window
    qs = (
        Article.objects.filter(status="processed")
        .select_related("source", "classification")
        .prefetch_related("classification__mentions")
        .order_by("-published_at", "-fetched_at")
    )
    if window_start and window_end:
        qs = qs.filter(
            Q(published_at__gte=window_start, published_at__lte=window_end)
            | Q(fetched_at__gte=window_start, fetched_at__lte=window_end)
        )
    return qs


def _section_watchlist_keys(filters: Iterable[SynthesisSectionFilter]) -> set[str]:
    watchlist = set()
    for item in filters:
        if item.persona_id:
            watchlist.add(f"persona:{item.persona_id}")
        if item.institucion_id:
            watchlist.add(f"institucion:{item.institucion_id}")
        if item.topic_id:
            watchlist.add(f"tema:{item.topic_id}")
    return watchlist


def _normalize_keywords(values: Iterable[str]) -> list[str]:
    normalized = []
    for value in values:
        variant = normalize_name(value or "")
        if variant:
            normalized.append(variant)
    return normalized


def _evaluate_section_contract(
    template: SynthesisSectionTemplate,
    article: Article,
    mention_strengths: list[SynthesisArticleMentionStrength],
) -> tuple[bool, float, dict]:
    filters = template.filters.select_related("persona", "institucion", "topic")
    watchlist_keys = _section_watchlist_keys(filters)
    strong_keys = {
        f"{ms.target_type}:{ms.target_id}" for ms in mention_strengths if ms.strength == "strong"
    }
    total_keys = {f"{ms.target_type}:{ms.target_id}" for ms in mention_strengths}
    strong_hits = sorted(watchlist_keys & strong_keys)
    total_hits = sorted(watchlist_keys & total_keys)

    normalized_text = normalize_name(f"{article.title} {article.text[:600]}")
    positive_keywords = _normalize_keywords(template.contract_keywords_positive or [])
    negative_keywords = _normalize_keywords(template.contract_keywords_negative or [])
    matched_positive = [kw for kw in positive_keywords if kw in normalized_text]
    matched_negative = [kw for kw in negative_keywords if kw in normalized_text]

    if matched_negative:
        return (
            False,
            0.0,
            {
                "reason": "negative_keyword",
                "matched_negative": matched_negative,
                "matched_positive": matched_positive,
            },
        )

    score = 0.0
    score += min(len(strong_hits) * 0.6, 1.0)
    score += min(len(total_hits) * 0.2, 0.6)
    if matched_positive:
        score += 0.2
    score = min(score, 1.0)

    min_score = template.contract_min_score or settings.SINTESIS_ROUTING_DEFAULT_MIN_SCORE
    min_mentions = template.contract_min_mentions or settings.SINTESIS_ROUTING_DEFAULT_MIN_MENTIONS
    is_included = bool(strong_hits) or (len(total_hits) >= min_mentions and score >= min_score)

    return (
        is_included,
        score,
        {
            "strong_hits": strong_hits,
            "total_hits": total_hits,
            "matched_positive": matched_positive,
            "matched_negative": matched_negative,
            "min_score": min_score,
            "min_mentions": min_mentions,
            "score": score,
        },
    )


def _store_mention_strengths(article: Article) -> list[SynthesisArticleMentionStrength]:
    classification = getattr(article, "classification", None)
    mentions = classification.mentions.all() if classification else []
    strengths = classify_mentions(article, mentions)
    SynthesisArticleMentionStrength.objects.filter(article=article).delete()
    records = [
        SynthesisArticleMentionStrength(
            article=article,
            target_type=item.target_type,
            target_id=item.target_id,
            target_name=item.target_name,
            strength=item.strength,
            positions_json=item.positions,
        )
        for item in strengths
    ]
    if records:
        SynthesisArticleMentionStrength.objects.bulk_create(records)
    return records


def _ensure_embedding_cache(article: Article) -> None:
    classification = getattr(article, "classification", None)
    labels = list(getattr(classification, "labels_json", []) or [])
    entity_names = []
    if classification:
        entity_names = [mention.target_name for mention in classification.mentions.all()]
    canonical_text = build_canonical_text(article, labels, entity_names)
    canonical_key = canonical_hash(canonical_text)
    cache = getattr(article, "embedding_cache", None)
    if cache and cache.canonical_hash == canonical_key:
        return
    embedding = []
    if settings.SINTESIS_ENABLE_EMBEDDINGS:
        embedding = compute_embedding(canonical_text)
    embedding_record, _created = SynthesisArticleEmbedding.objects.update_or_create(
        article=article,
        defaults={
            "canonical_hash": canonical_key,
            "canonical_text": canonical_text,
            "embedding_json": embedding or (cache.embedding_json if cache else []),
        },
    )
    if embedding:
        update_embedding_vector(embedding_record.id, embedding)


def route_articles_for_section(
    run: SynthesisRun,
    template: SynthesisSectionTemplate,
    window: Tuple[datetime, datetime],
) -> list[Article]:
    candidates = _fetch_window_articles(window)
    routing_rows = []
    included = []

    for article in candidates:
        _ensure_embedding_cache(article)
        strengths = _store_mention_strengths(article)
        is_included, score, details = _evaluate_section_contract(template, article, strengths)
        routing_rows.append(
            SynthesisSectionRoutingResult(
                run=run,
                template=template,
                article=article,
                is_included=is_included,
                score=score,
                scores_json=details,
            )
        )
        if is_included:
            included.append(article)

    if routing_rows:
        SynthesisSectionRoutingResult.objects.bulk_create(routing_rows)
    if settings.SINTESIS_ENABLE_DEDUPE:
        return _dedupe_articles(run, included)
    return included


def _dedupe_key_for_article(article: Article) -> str:
    url_key = normalize_name(article.url or "")
    cache = getattr(article, "embedding_cache", None)
    canonical_key = cache.canonical_hash if cache else ""
    base = f"{url_key}|{canonical_key}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _dedupe_articles(run: SynthesisRun, articles: list[Article]) -> list[Article]:
    seen_keys = set()
    dedupe_rows = []
    kept = []
    for article in articles:
        dedupe_key = _dedupe_key_for_article(article)
        if dedupe_key in seen_keys:
            dedupe_rows.append(
                SynthesisArticleDedup(
                    run=run,
                    article=article,
                    dedup_key=dedupe_key,
                    reason="duplicate_in_run",
                )
            )
            continue
        seen_keys.add(dedupe_key)
        kept.append(article)
    if dedupe_rows:
        SynthesisArticleDedup.objects.bulk_create(dedupe_rows)
    return kept


def cluster_articles_into_stories(articles: Sequence[Article]):
    profiles = [build_profile(article) for article in articles]
    return group_profiles(profiles)


def build_clusters_for_section(
    run: SynthesisRun,
    template: SynthesisSectionTemplate,
    articles: List[Article],
) -> List[SynthesisCluster]:
    return assign_articles_to_clusters(run, template, articles)


def _group_metrics(profiles) -> Tuple[int, List[str], dict, dict, dict]:
    sources = [profile.article.source.name for profile in profiles if profile.article.source]
    source_counts = Counter(sources)
    type_counts = Counter()
    sentiment_counts = Counter()
    for profile in profiles:
        classification = getattr(profile.article, "classification", None)
        if classification and classification.article_type:
            type_counts[classification.article_type] += 1
        if classification:
            for mention in classification.mentions.all():
                if mention.sentiment:
                    sentiment_counts[mention.sentiment] += 1
    return (
        len(profiles),
        sorted(source_counts.keys()),
        dict(source_counts),
        dict(type_counts),
        dict(sentiment_counts),
    )


def generate_story_title_and_summary(
    cluster_articles: Sequence[Article],
    optional_section_prompt: Optional[str] = None,
    optional_review_text: Optional[str] = None,
) -> Tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    project_id = os.getenv("OPENAI_PROJECT_ID")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    profiles = [build_profile(article) for article in cluster_articles]
    if not profiles:
        return "Síntesis sin artículos", "No hay notas asociadas."

    if not api_key:
        title = profiles[0].article.title
        summary = profiles[0].central_idea or profiles[0].article.text[:180]
        return _clip_words(title, 14), _clip_words(summary, 45)

    if api_key.startswith("sk-proj-") and not project_id:
        raise RuntimeError("OPENAI_PROJECT_ID es requerido para claves sk-proj-*.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, project=project_id)
    titles = [profile.article.title for profile in profiles[:6]]
    central_idea = profiles[0].central_idea
    labels = list({label for profile in profiles for label in profile.labels})[:8]
    mentions = list({mention for profile in profiles for mention in profile.mentions})[:8]
    prompt_extra = ""
    if optional_section_prompt:
        prompt_extra += f"\nContexto de sección: {optional_section_prompt}\n"
    if optional_review_text:
        prompt_extra += f"\nNotas editoriales: {optional_review_text}\n"

    prompt = f"""
Eres un editor experto de noticias. Tu tarea es sintetizar este grupo de artículos en una historia cohesiva.

Instrucciones:
1. Analiza los titulares y la Idea Central.
2. Escribe un TÍTULO corto y atractivo (10-14 palabras).
3. Escribe un RESUMEN (30-50 palabras).
4. Tono periodístico, neutral y directo.
5. Devuelve SOLO un objeto JSON válido.

{prompt_extra}
Insumos:
- Idea central: {central_idea}
- Etiquetas IA: {", ".join(labels)}
- Menciones: {", ".join(mentions)}
- Titulares: {" | ".join(titles)}
- Fecha del reporte: {timezone.now().strftime("%d/%m/%Y")}

Schema JSON esperado:
{{
  "title": "string",
  "summary": "string"
}}
""".strip()

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Responde solo JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or ""
    payload = parse_json_response(raw)
    title = payload.get("title") or profiles[0].article.title
    summary = payload.get("summary") or profiles[0].central_idea or profiles[0].article.text[:160]
    return _clip_words(title, 14), _clip_words(summary, 50)


def _clip_words(text: str, limit: int) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return text.strip()
    return " ".join(words[:limit]).strip()


def make_story_fingerprint(cluster_articles: Sequence[Article], central_idea: str = "") -> str:
    idea = normalize_name(central_idea or "")
    article_ids = ",".join(str(article.id) for article in sorted(cluster_articles, key=lambda a: a.id))
    base = f"{idea}|{article_ids}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def persist_run(
    run: SynthesisRun,
    section_payloads: Sequence[dict],
) -> int:
    created_stories = 0
    run_sources = set()
    log_lines: List[str] = []

    for section_payload in section_payloads:
        section = SynthesisRunSection.objects.create(
            run=run,
            template=section_payload.get("template"),
            title=section_payload["title"],
            order=section_payload["order"],
            group_by=section_payload["group_by"],
            review_text=section_payload.get("review_text", ""),
            prompt_snapshot=section_payload.get("prompt_snapshot", ""),
        )
        stories_payloads = section_payload.get("stories", [])
        if not stories_payloads:
            section.delete()
            continue

        section_story_count = 0
        section_article_count = 0
        section_sources = set()

        for payload in stories_payloads:
            with transaction.atomic():
                story = SynthesisStory.objects.create(
                    client=run.client,
                    run=run,
                    run_section=section,
                    title=payload["title"],
                    summary=payload["summary"],
                    central_idea=payload.get("central_idea", ""),
                    labels_json=payload.get("labels_json", []),
                    group_signals_json=payload.get("signals", []),
                    article_count=payload.get("article_count", 0),
                    unique_sources_count=payload.get("unique_sources_count", 0),
                    source_names_json=payload.get("source_names", []),
                    type_counts_json=payload.get("type_counts", {}),
                    sentiment_counts_json=payload.get("sentiment_counts", {}),
                    group_label=payload.get("group_label", ""),
                    date_from=run.window_start.date() if run.window_start else None,
                    date_to=run.window_end.date() if run.window_end else None,
                    story_fingerprint=payload["story_fingerprint"],
                )
                for article in payload.get("articles", []):
                    SynthesisStoryArticle.objects.create(
                        story=story,
                        article=article,
                        source_name=article.source.name if article.source else "",
                        source_url=article.url,
                        published_at=article.published_at,
                    )
            created_stories += 1
            section_story_count += 1
            section_article_count += payload.get("article_count", 0)
            section_sources.update(payload.get("source_names", []))
            run_sources.update(payload.get("source_names", []))

        section.stats_json = {
            "stories": section_story_count,
            "articles": section_article_count,
            "sources": len(section_sources),
        }
        section.save(update_fields=["stats_json"])
        log_lines.append(f"{section.title}: {section_story_count} historias")

    run.output_count = created_stories
    run.stats_json = {
        "sources": sorted(run_sources),
        "sections": [payload["title"] for payload in section_payloads if payload.get("stories")],
        "routing": routing_counts,
        "dedupe": dedupe_counts,
        "clusters": cluster_counts,
        "metrics": _build_run_metrics(
            routing_counts,
            dedupe_counts,
            _cluster_purity_by_template(run),
        ),
    }
    run.log_text = "\n".join(log_lines)
    run.save(update_fields=["output_count", "stats_json", "log_text"])
    return created_stories


def render_run_to_html_snapshot(run_id: int) -> str:
    run = SynthesisRun.objects.select_related("client").get(pk=run_id)
    ordered_stories = SynthesisStory.objects.order_by(
        "group_label",
        "-created_at",
        "id",
    ).prefetch_related("story_articles")
    sections = (
        SynthesisRunSection.objects.filter(run=run)
        .prefetch_related(Prefetch("stories", queryset=ordered_stories))
        .order_by("order", "id")
    )
    date_str = timezone.localtime(run.started_at).strftime("%d/%m/%Y - %H:%M")
    return render_to_string(
        "sintesis/run_document.html",
        {
            "run": run,
            "client": run.client,
            "sections": sections,
            "date_str": date_str,
            "sources": run.stats_json.get("sources", []),
        },
    )


def generate_pdf(run_id: int) -> Optional[FieldFile]:
    if not settings.SINTESIS_ENABLE_PDF:
        return None
    run = SynthesisRun.objects.get(pk=run_id)
    html = render_run_to_html_snapshot(run_id)
    try:
        from weasyprint import HTML
    except ImportError:
        logger.warning("WeasyPrint not available. PDF generation skipped.")
        return None
    html_obj = HTML(string=html, base_url=str(settings.BASE_DIR))
    try:
        pdf_bytes = html_obj.write_pdf()
    except Exception:  # noqa: BLE001
        logger.exception("Error generating PDF for run %s", run_id)
        return None
    filename = f"sintesis_{run.client_id}_{run.pk}.pdf"
    run.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
    run.pdf_generated_at = timezone.now()
    run.save(update_fields=["pdf_file", "pdf_generated_at"])
    return run.pdf_file


def build_section_payloads(
    run: SynthesisRun,
    templates: Sequence[SynthesisSectionTemplate],
    window: Tuple[datetime, datetime],
    review_text: Optional[str] = None,
) -> List[dict]:
    used_fingerprints = set()
    section_payloads: List[dict] = []
    routing_counts: dict[int, dict[str, int]] = {}
    dedupe_counts: dict[int, int] = {}
    cluster_counts: dict[int, int] = {}

    for template in templates:
        filters = template.filters.select_related("persona", "institucion", "topic")
        if settings.SINTESIS_ENABLE_NEW_PIPELINE:
            articles = route_articles_for_section(run, template, window)
            routing_counts[template.id] = {
                "included": len(articles),
                "total": SynthesisSectionRoutingResult.objects.filter(
                    run=run,
                    template=template,
                ).count(),
            }
            dedupe_counts[template.id] = SynthesisArticleDedup.objects.filter(
                run=run,
                article__in=articles,
            ).count()
        else:
            articles = list(fetch_candidate_articles(window, filters))
        if not articles:
            continue
        if settings.SINTESIS_ENABLE_NEW_PIPELINE:
            build_clusters_for_section(run, template, articles)
            if settings.SINTESIS_ENABLE_LLM_LABELS:
                label_clusters(run.id, template.id)
            cluster_counts[template.id] = SynthesisCluster.objects.filter(
                run=run,
                template=template,
            ).count()
        groups = cluster_articles_into_stories(articles)
        groups = _rank_and_limit_groups(groups, template)
        stories_payloads = []
        for group in groups:
            profiles = group.get("profiles", [])
            cluster_articles = [profile.article for profile in profiles]
            if not cluster_articles:
                continue
            central_idea = profiles[0].central_idea if profiles else ""
            fingerprint = make_story_fingerprint(cluster_articles, central_idea)
            if fingerprint in used_fingerprints:
                continue
            title, summary = generate_story_title_and_summary(
                cluster_articles,
                optional_section_prompt=template.section_prompt,
                optional_review_text=review_text,
            )
            article_count, source_names, source_counts, type_counts, sentiment_counts = _group_metrics(
                profiles
            )
            group_label = ""
            if template.section_type == "by_institution":
                group_label = _dominant_institution_label(profiles)
            stories_payloads.append(
                {
                    "title": title,
                    "summary": summary,
                    "central_idea": central_idea,
                    "labels_json": list(group.get("labels", [])),
                    "signals": list(group.get("signals", [])),
                    "article_count": article_count,
                    "unique_sources_count": len(source_names),
                    "source_names": source_names,
                    "type_counts": type_counts,
                    "sentiment_counts": sentiment_counts,
                    "group_label": group_label,
                    "articles": cluster_articles,
                    "story_fingerprint": fingerprint,
                }
            )
            used_fingerprints.add(fingerprint)
        if stories_payloads:
            section_payloads.append(
                {
                    "template": template,
                    "title": template.title,
                    "order": template.order,
                    "group_by": template.group_by,
                    "prompt_snapshot": template.section_prompt,
                    "review_text": "",
                    "stories": stories_payloads,
                }
            )
    return section_payloads


def _rank_and_limit_groups(groups: List[dict], template: SynthesisSectionTemplate) -> List[dict]:
    def group_score(group: dict) -> tuple:
        profiles = group.get("profiles", [])
        article_count = len(profiles)
        sources = {profile.article.source_id for profile in profiles if profile.article.source_id}
        source_count = len(sources)
        latest = max(
            [
                profile.article.published_at or profile.article.fetched_at
                for profile in profiles
                if profile.article
            ],
            default=timezone.now(),
        )
        return (article_count, source_count, latest)

    ranked = sorted(groups, key=group_score, reverse=True)
    limit = getattr(settings, "SINTESIS_SECTION_STORY_LIMIT", 6)
    return ranked[:limit]


def _build_run_metrics(
    routing_counts: dict[int, dict[str, int]],
    dedupe_counts: dict[int, int],
    cluster_purity: dict[int, float],
) -> dict:
    off_section_rate = {}
    dup_rate = {}
    for template_id, counts in routing_counts.items():
        total = counts.get("total", 0)
        included = counts.get("included", 0)
        if total:
            off_section_rate[template_id] = round((total - included) / total, 4)
        else:
            off_section_rate[template_id] = 0.0
        if included:
            dup_rate[template_id] = round(dedupe_counts.get(template_id, 0) / included, 4)
        else:
            dup_rate[template_id] = 0.0
    return {
        "off_section_rate": off_section_rate,
        "dup_rate": dup_rate,
        "cluster_purity": cluster_purity,
    }


def _cluster_purity_by_template(run: SynthesisRun) -> dict[int, float]:
    purities = {}
    clusters = (
        SynthesisCluster.objects.filter(run=run)
        .prefetch_related("members__article__classification__mentions")
        .order_by("template_id")
    )
    purity_scores = {}
    cluster_counts = {}

    for cluster in clusters:
        member_count = cluster.members.count()
        if not member_count:
            continue
        entity_counts = Counter()
        for member in cluster.members.all():
            strengths = SynthesisArticleMentionStrength.objects.filter(
                article=member.article,
                strength="strong",
            )
            for item in strengths:
                key = f"{item.target_type}:{item.target_id}"
                entity_counts[key] += 1
        if not entity_counts:
            purity = 0.0
        else:
            dominant = entity_counts.most_common(1)[0][1]
            purity = dominant / member_count

        template_id = cluster.template_id
        purity_scores[template_id] = purity_scores.get(template_id, 0.0) + purity
        cluster_counts[template_id] = cluster_counts.get(template_id, 0) + 1

    for template_id, total in purity_scores.items():
        purities[template_id] = round(total / cluster_counts[template_id], 4)
    return purities


def _dominant_institution_label(profiles) -> str:
    counts = Counter()
    for profile in profiles:
        classification = getattr(profile.article, "classification", None)
        if not classification:
            continue
        for mention in classification.mentions.all():
            if mention.target_type == "institucion":
                counts[mention.target_name] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]
