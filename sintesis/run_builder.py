from __future__ import annotations

import importlib
import importlib.util
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import transaction
from django.db.models import Prefetch, Q
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from atlas_core.text_utils import normalize_name, tokenize
from monitor.models import Article
from sintesis.models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisRun,
    SynthesisRunSection,
    SynthesisSectionTemplate,
    SynthesisStory,
    SynthesisStoryArticle,
)
from sintesis.services import build_profile, generate_story_text, group_profiles, jaccard_similarity


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectionSpec:
    title: str
    order: int
    group_by: str
    template: Optional[SynthesisSectionTemplate]
    section_type: str
    personas: Set[int]
    instituciones: Set[int]
    topics: Set[int]
    tokens: Set[str]


def resolve_date_range(date_from, date_to):
    if date_from and date_to:
        return date_from, date_to
    if date_from and not date_to:
        return date_from, date_from
    if date_to and not date_from:
        return date_to, date_to
    today = timezone.now().date()
    return today - timedelta(days=1), today


def _article_in_range(queryset, date_from, date_to):
    if not date_from and not date_to:
        return queryset
    return queryset.filter(
        Q(published_at__date__gte=date_from, published_at__date__lte=date_to)
        | Q(fetched_at__date__gte=date_from, fetched_at__date__lte=date_to)
    )


def _keyword_tokens(client: SynthesisClient) -> Set[str]:
    keywords = client.keyword_tags or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]
    return {normalize_name(word) for word in keywords if word}


def _tokenize_values(values: Iterable[str]) -> Set[str]:
    tokens: Set[str] = set()
    for value in values:
        if not value:
            continue
        tokens.update(tokenize(value))
    return tokens


def _extract_interest_targets(interests: Iterable[SynthesisClientInterest]) -> Tuple[Set[int], Set[int], Set[int], Set[str]]:
    personas: Set[int] = set()
    instituciones: Set[int] = set()
    topics: Set[int] = set()
    tokens: Set[str] = set()
    for interest in interests:
        if interest.persona_id:
            personas.add(interest.persona_id)
            tokens.update(_tokenize_values([interest.persona.nombre_completo]))
        if interest.institucion_id:
            instituciones.add(interest.institucion_id)
            tokens.update(_tokenize_values([interest.institucion.nombre]))
        if interest.topic_id:
            topics.add(interest.topic_id)
            tokens.update(_tokenize_values([interest.topic.name]))
    return personas, instituciones, topics, tokens


def _extract_section_filters(
    template: SynthesisSectionTemplate,
) -> Tuple[Set[int], Set[int], Set[int], Set[str]]:
    personas: Set[int] = set()
    instituciones: Set[int] = set()
    topics: Set[int] = set()
    tokens: Set[str] = set()
    filters = template.filters.select_related("persona", "institucion", "topic")
    for item in filters:
        if item.persona_id:
            personas.add(item.persona_id)
            tokens.update(_tokenize_values([item.persona.nombre_completo]))
        if item.institucion_id:
            instituciones.add(item.institucion_id)
            tokens.update(_tokenize_values([item.institucion.nombre]))
        if item.topic_id:
            topics.add(item.topic_id)
            tokens.update(_tokenize_values([item.topic.name]))
        # Keywords support
        if hasattr(item, "keywords") and item.keywords:
            raw_keywords = [k.strip() for k in item.keywords.split(",") if k.strip()]
            tokens.update(_tokenize_values(raw_keywords))
    return personas, instituciones, topics, tokens


def _build_section_specs(client: SynthesisClient) -> List[SectionSpec]:
    priority_interests = client.interests.filter(interest_group="priority").select_related(
        "persona", "institucion", "topic"
    )
    general_interests = client.interests.filter(interest_group="general").select_related(
        "persona", "institucion", "topic"
    )

    priority_personas, priority_instituciones, priority_topics, priority_tokens = (
        _extract_interest_targets(priority_interests)
    )
    general_personas, general_instituciones, general_topics, general_tokens = (
        _extract_interest_targets(general_interests)
    )

    if client.persona_id:
        priority_personas.add(client.persona_id)
        priority_tokens.update(_tokenize_values([client.persona.nombre_completo]))
    if client.institucion_id:
        priority_instituciones.add(client.institucion_id)
        priority_tokens.update(_tokenize_values([client.institucion.nombre]))

    # Check if there is already a custom section for "Notas principales" (order < 100 or check title)
    # We load templates first to check
    templates = (
        client.section_templates.filter(is_active=True)
        .prefetch_related("filters")
        .order_by("order", "id")
    )
    
    # Heuristic: If any template has order < 50, we assume the user is controlling the top sections manually.
    # Otherwise, we inject the legacy "Notas principales" at order 10.
    has_custom_main = any(t.order < 50 for t in templates)

    specs: List[SectionSpec] = []

    if not has_custom_main and (priority_personas or priority_instituciones or priority_topics):
         specs.append(
            SectionSpec(
                title="Notas principales",
                order=10,
                group_by="story",
                template=None,
                section_type="priority",
                personas=priority_personas,
                instituciones=priority_instituciones,
                topics=priority_topics,
                tokens=priority_tokens,
            )
        )

    for template in templates:
        personas, instituciones, topics, tokens = _extract_section_filters(template)
        specs.append(
            SectionSpec(
                title=template.title,
                order=template.order, # Use exact order from DB
                group_by=template.group_by,
                template=template,
                section_type=template.section_type,
                personas=personas,
                instituciones=instituciones,
                topics=topics,
                tokens=tokens,
            )
        )

    specs.append(
        SectionSpec(
            title="Notas generales",
            order=900,
            group_by="institution",
            template=None,
            section_type="general",
            personas=general_personas,
            instituciones=general_instituciones,
            topics=general_topics,
            tokens=general_tokens,
        )
    )
    return specs


def _matches_section(
    article: Article,
    spec: SectionSpec,
    keyword_tokens: Set[str],
) -> bool:
    classification = getattr(article, "classification", None)
    if not classification:
        return False

    mentions = classification.mentions.all()
    for mention in mentions:
        if mention.target_type == "persona" and mention.target_id in spec.personas:
            return True
        if mention.target_type == "institucion" and mention.target_id in spec.instituciones:
            return True
        if mention.target_type == "tema" and mention.target_id in spec.topics:
            return True

    text_blob = " ".join(
        [
            classification.central_idea or "",
            article.title or "",
            " ".join(classification.labels_json or []),
        ]
    )
    normalized_blob = normalize_name(text_blob)
    for token in spec.tokens:
        if token and token in normalized_blob:
            return True

    if keyword_tokens:
        labels = [normalize_name(label) for label in classification.labels_json or []]
        for keyword in keyword_tokens:
            if keyword in labels or keyword in normalized_blob:
                return True
    return False


def _extract_client_criteria(
    client: SynthesisClient,
) -> Tuple[Set[int], Set[int], Set[int], Set[str]]:
    interests = client.interests.select_related("persona", "institucion", "topic").all()
    personas, instituciones, topics, _tokens = _extract_interest_targets(interests)
    if client.persona_id:
        personas.add(client.persona_id)
    if client.institucion_id:
        instituciones.add(client.institucion_id)
    keyword_tokens = _keyword_tokens(client)
    return personas, instituciones, topics, keyword_tokens


def _matches_client_criteria(
    article: Article,
    personas: Set[int],
    instituciones: Set[int],
    topics: Set[int],
    keyword_tokens: Set[str],
) -> bool:
    classification = getattr(article, "classification", None)
    if not classification:
        return False

    mentions = classification.mentions.all()
    for mention in mentions:
        if mention.target_type == "persona" and mention.target_id in personas:
            return True
        if mention.target_type == "institucion" and mention.target_id in instituciones:
            return True
        if mention.target_type == "tema" and mention.target_id in topics:
            return True

    if not keyword_tokens:
        return False

    text_blob = " ".join(
        [
            classification.central_idea or "",
            article.title or "",
            " ".join(classification.labels_json or []),
        ]
    )
    normalized_blob = normalize_name(text_blob)
    labels = [normalize_name(label) for label in classification.labels_json or []]
    for keyword in keyword_tokens:
        if keyword in labels or keyword in normalized_blob:
            return True
    return False


def _institution_key(article: Article, spec: SectionSpec) -> Optional[str]:
    classification = getattr(article, "classification", None)
    if not classification:
        return None
    has_institution_mentions = False
    for mention in classification.mentions.all():
        if mention.target_type != "institucion":
            continue
        has_institution_mentions = True
        if spec.instituciones and mention.target_id not in spec.instituciones:
            continue
        return mention.target_name
    if not spec.instituciones and not has_institution_mentions:
        return "Sin institución"
    return None


def _article_sentiment(classification) -> str:
    if not classification:
        return "neutro"
    mention = classification.mentions.first()
    if mention and mention.sentiment:
        return mention.sentiment
    return "neutro"


def _build_story_metrics(profiles: Sequence) -> Tuple[int, List[str], Dict[str, int], Dict[str, int]]:
    type_counts: Counter = Counter()
    sentiment_counts: Counter = Counter()
    sources: Set[str] = set()

    for profile in profiles:
        article = profile.article
        classification = getattr(article, "classification", None)
        # Compatibilidad: si no hay article_type/sentiment en Monitor aún, contamos como cero.
        if classification and classification.article_type:
            type_counts[classification.article_type] += 1
        sentiment = _article_sentiment(classification)
        sentiment_counts[sentiment] += 1
        if article.source:
            sources.add(article.source.name)

    return (
        len(sources),
        sorted(sources),
        {
            "informativo": type_counts.get("informativo", 0),
            "opinion": type_counts.get("opinion", 0),
        },
        {
            "positivo": sentiment_counts.get("positivo", 0),
            "neutro": sentiment_counts.get("neutro", 0),
            "negativo": sentiment_counts.get("negativo", 0),
        },
    )


def _group_signature_tokens(group: dict) -> Set[str]:
    tokens: Set[str] = set()
    tokens.update(group.get("title_tokens", set()))
    tokens.update(group.get("idea_tokens", set()))
    return tokens


def build_run(
    client: SynthesisClient,
    date_from=None,
    date_to=None,
    schedule=None,
    run_type: str = "manual",
    status: str = "running",
) -> SynthesisRun:
    date_from, date_to = resolve_date_range(date_from, date_to)
    run = SynthesisRun.objects.create(
        client=client,
        schedule=schedule,
        run_type=run_type,
        date_from=date_from,
        date_to=date_to,
        status=status,
    )
    logger.info("Iniciando run de síntesis %s para %s", run.pk, client.name)
    return run


def build_run_document(run: SynthesisRun) -> int:
    client = run.client
    section_specs = _build_section_specs(client)
    keyword_tokens = _keyword_tokens(client)
    personas, instituciones, topics, criteria_keywords = _extract_client_criteria(client)
    has_criteria = bool(personas or instituciones or topics or criteria_keywords)

    article_queryset = (
        Article.objects.filter(status="processed")
        .select_related("source", "classification")
        .prefetch_related("classification__mentions")
        .order_by("-published_at", "-fetched_at")
    )
    if has_criteria:
        article_queryset = _article_in_range(article_queryset, run.date_from, run.date_to)
    else:
        cutoff = timezone.now() - timedelta(hours=24)
        article_queryset = article_queryset.filter(
            Q(published_at__gte=cutoff) | Q(fetched_at__gte=cutoff)
        )[:200]

    article_list = list(article_queryset)
    if has_criteria:
        article_list = [
            article
            for article in article_list
            if _matches_client_criteria(
                article,
                personas,
                instituciones,
                topics,
                criteria_keywords,
            )
        ]

    assigned_article_ids: Set[int] = set()
    seen_story_signatures: List[Set[str]] = []
    dedupe_threshold = getattr(settings, "SINTESIS_STORY_DEDUP_THRESHOLD", 0.62)
    created_stories = 0
    run_sections: List[SynthesisRunSection] = []
    run_sources: Set[str] = set()
    log_lines: List[str] = []

    for spec in section_specs:
        if has_criteria and not (
            spec.personas or spec.instituciones or spec.topics or spec.tokens or keyword_tokens
        ):
            continue
        matching_articles = []
        for article in article_list:
            if article.id in assigned_article_ids:
                continue
            if not has_criteria:
                matching_articles.append(article)
            elif _matches_section(article, spec, keyword_tokens):
                matching_articles.append(article)

        if not matching_articles:
            continue

        section = SynthesisRunSection.objects.create(
            run=run,
            template=spec.template,
            title=spec.title,
            order=spec.order,
            group_by=spec.group_by,
            stats_json={},
        )

        if spec.group_by == "institution":
            grouped_articles: Dict[str, List[Article]] = defaultdict(list)
            for article in matching_articles:
                key = _institution_key(article, spec)
                if not key:
                    continue
                grouped_articles[key].append(article)
            group_items = grouped_articles.items()
        else:
            group_items = [(None, matching_articles)]

        section_story_count = 0
        section_article_count = 0
        section_sources: Set[str] = set()
        for group_label, group_articles in group_items:
            profiles = [build_profile(article) for article in group_articles]
            groups = group_profiles(profiles)
            for group in groups:
                profiles = group["profiles"]
                signature_tokens = _group_signature_tokens(group)
                if signature_tokens:
                    is_duplicate = any(
                        jaccard_similarity(signature_tokens, seen_tokens) >= dedupe_threshold
                        for seen_tokens in seen_story_signatures
                    )
                    if is_duplicate:
                        for profile in profiles:
                            assigned_article_ids.add(profile.article.id)
                        continue
                story_text = generate_story_text(group)
                unique_sources_count, source_names, type_counts, sentiment_counts = (
                    _build_story_metrics(profiles)
                )
                with transaction.atomic():
                    story = SynthesisStory.objects.create(
                        client=client,
                        run=run,
                        run_section=section,
                        title=story_text["title"],
                        summary=story_text["summary"],
                        central_idea=profiles[0].central_idea if profiles else "",
                        labels_json=list(group["labels"]),
                        group_signals_json=group.get("signals", []),
                        article_count=len(profiles),
                        unique_sources_count=unique_sources_count,
                        source_names_json=source_names,
                        type_counts_json=type_counts,
                        sentiment_counts_json=sentiment_counts,
                        group_label=group_label or "",
                        date_from=run.date_from,
                        date_to=run.date_to,
                    )
                    for profile in profiles:
                        article = profile.article
                        SynthesisStoryArticle.objects.create(
                            story=story,
                            article=article,
                            source_name=article.source.name,
                            source_url=article.url,
                            published_at=article.published_at,
                        )
                        assigned_article_ids.add(article.id)
                created_stories += 1
                section_story_count += 1
                section_article_count += len(profiles)
                section_sources.update(source_names)
                run_sources.update(source_names)
                if signature_tokens:
                    seen_story_signatures.append(signature_tokens)

        if section_story_count:
            section.stats_json = {
                "stories": section_story_count,
                "articles": section_article_count,
                "sources": len(section_sources),
            }
            section.save(update_fields=["stats_json"])
            run_sections.append(section)
            log_lines.append(f"{section.title}: {section_story_count} historias")
        else:
            section.delete()

    run.output_count = created_stories
    run.stats_json = {
        "sources": sorted(run_sources),
        "sections": [section.title for section in run_sections],
    }
    run.log_text = "\n".join(log_lines)

    if created_stories:
        html_snapshot = render_run_html(run, is_pdf=False)
        run.html_snapshot = html_snapshot
        pdf_file = generate_run_pdf(run)
        if pdf_file:
            run.pdf_file = pdf_file
            run.pdf_generated_at = timezone.now()

    run.save(
        update_fields=[
            "output_count",
            "stats_json",
            "log_text",
            "html_snapshot",
            "pdf_file",
            "pdf_generated_at",
        ]
    )
    return created_stories


def render_run_html(run: SynthesisRun, is_pdf: bool = False) -> str:
    now_local = timezone.localtime(run.started_at)
    date_str = now_local.strftime("%d/%m/%Y - %H:%M")
    logo_name = "img/logo-Horizonte-sintesis-light.png" if is_pdf else "img/logo-Horizonte-sintesis-dark.png"
    css_name = "css/sintesis_document.css"
    css_path = finders.find(css_name)
    logo_path = finders.find(logo_name)
    if css_path:
        css_href = f"file://{css_path}" if is_pdf else settings.STATIC_URL + css_name
    else:
        css_href = settings.STATIC_URL + css_name
    if logo_path:
        logo_href = f"file://{logo_path}" if is_pdf else settings.STATIC_URL + logo_name
    else:
        logo_href = settings.STATIC_URL + logo_name

    ordered_stories = SynthesisStory.objects.order_by(
        "group_label",
        "-created_at",
        "id",
    ).prefetch_related("story_articles")
    sections = (
        run.sections.prefetch_related(Prefetch("stories", queryset=ordered_stories))
        .order_by("order", "id")
        .all()
    )
    return render_to_string(
        "sintesis/run_document.html",
        {
            "run": run,
            "client": run.client,
            "sections": sections,
            "date_str": date_str,
            "sources": run.stats_json.get("sources", []),
            "css_href": css_href,
            "logo_href": logo_href,
            "is_pdf": is_pdf,
        },
    )


def _weasyprint_available() -> bool:
    return importlib.util.find_spec("weasyprint") is not None


def generate_run_pdf(run: SynthesisRun) -> Optional[str]:
    if not settings.SINTESIS_ENABLE_PDF:
        return None
    if not _weasyprint_available():
        logger.warning("WeasyPrint not available. PDF generation will be disabled.")
        return None
    if not run.output_count:
        return None
    html = render_run_html(run, is_pdf=True)
    weasyprint_module = importlib.import_module("weasyprint")
    html_obj = weasyprint_module.HTML(string=html, base_url=str(settings.BASE_DIR))
    try:
        pdf_bytes = html_obj.write_pdf()
    except Exception:  # noqa: BLE001
        logger.exception("Error generating PDF for run %s.", run.pk)
        return None
    filename = f"sintesis_{run.client_id}_{run.pk}.pdf"
    run.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
    return run.pdf_file


def ensure_run_pdf(run: SynthesisRun) -> Optional[str]:
    if run.pdf_file:
        return run.pdf_file
    if not settings.SINTESIS_ENABLE_PDF:
        return None
    if not run.output_count:
        return None
    pdf_file = generate_run_pdf(run)
    if pdf_file:
        run.pdf_generated_at = timezone.now()
        run.save(update_fields=["pdf_file", "pdf_generated_at"])
    return pdf_file
