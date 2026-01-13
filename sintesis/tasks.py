import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from sintesis.models import SynthesisRun, SynthesisSchedule, SynthesisSectionTemplate
from sintesis.services.pipeline import (
    build_run_window,
    build_section_payloads,
    generate_pdf as generate_pdf_service,
    persist_run,
    render_run_to_html_snapshot,
)

logger = logging.getLogger(__name__)


def _next_run_datetime(schedule: SynthesisSchedule, from_dt: datetime) -> datetime:
    tz = ZoneInfo(schedule.timezone or "America/Mexico_City")
    local_dt = timezone.localtime(from_dt, tz)
    days = schedule.days_of_week or []
    if not days:
        days = list(range(7))

    for offset in range(0, 8):
        candidate_date = (local_dt + timedelta(days=offset)).date()
        weekday_index = (candidate_date.weekday())  # Monday=0
        if weekday_index not in days:
            continue
        candidate_dt = datetime.combine(candidate_date, schedule.run_time, tzinfo=tz)
        if candidate_dt > local_dt:
            return candidate_dt.astimezone(timezone.get_current_timezone())
    return (local_dt + timedelta(days=1)).astimezone(timezone.get_current_timezone())


@shared_task
def dispatch_due_schedules():
    now = timezone.now()
    schedules = (
        SynthesisSchedule.objects.filter(is_active=True, next_run_at__lte=now)
        .select_related("client")
        .order_by("next_run_at")
    )
    for schedule in schedules:
        generate_synthesis_run.delay(schedule_id=schedule.id)
        schedule.last_run_at = now
        schedule.next_run_at = _next_run_datetime(schedule, now)
        schedule.save(update_fields=["last_run_at", "next_run_at"])
    return schedules.count()


@shared_task
def generate_synthesis_run(
    schedule_id: int | None = None,
    client_id: int | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    regeneration_run_id: int | None = None,
    regeneration_template_id: int | None = None,
):
    schedule = None
    client = None
    if schedule_id:
        schedule = SynthesisSchedule.objects.select_related("client").get(pk=schedule_id)
        client = schedule.client
    elif client_id:
        from sintesis.models import SynthesisClient

        client = SynthesisClient.objects.get(pk=client_id)

    if regeneration_run_id:
        return _regenerate_section(regeneration_run_id, regeneration_template_id)

    if not client:
        raise ValueError("Debe especificar un cliente o programación.")

    start_dt = timezone.make_aware(datetime.fromisoformat(window_start)) if window_start else None
    end_dt = timezone.make_aware(datetime.fromisoformat(window_end)) if window_end else None
    window_start_dt, window_end_dt = build_run_window(
        schedule=schedule,
        window_start=start_dt,
        window_end=end_dt,
    )

    run = SynthesisRun.objects.create(
        client=client,
        schedule=schedule,
        run_type="scheduled" if schedule else "manual",
        status="running",
        window_start=window_start_dt,
        window_end=window_end_dt,
        date_from=window_start_dt.date(),
        date_to=window_end_dt.date(),
    )

    try:
        templates = (
            SynthesisSectionTemplate.objects.filter(client=client, is_active=True)
            .prefetch_related("filters")
            .order_by("order", "id")
        )
        if not templates:
            logger.info(
                "No section templates found for client %s. Falling back to legacy run builder.",
                client.id,
            )
            from sintesis.run_builder import build_run_document

            build_run_document(run)
        else:
            section_payloads = build_section_payloads(run, templates, (window_start_dt, window_end_dt))
            persist_run(run, section_payloads)
            html_snapshot = render_run_to_html_snapshot(run.id)
            run.html_snapshot = html_snapshot
        run.status = "completed"
        run.finished_at = timezone.now()
        run.save(update_fields=["html_snapshot", "status", "finished_at"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error al generar síntesis")
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    return run.id


def _regenerate_section(run_id: int, template_id: int | None):
    original = (
        SynthesisRun.objects.select_related("client")
        .prefetch_related("sections__stories__story_articles", "sections__template")
        .get(pk=run_id)
    )
    new_run = SynthesisRun.objects.create(
        client=original.client,
        schedule=original.schedule,
        run_type=original.run_type,
        parent_run=original,
        version=original.version + 1,
        regeneration_scope="section",
        regenerated_template_id=template_id,
        status="running",
        window_start=original.window_start,
        window_end=original.window_end,
    )

    templates = {
        section.template_id: section.template for section in original.sections.all() if section.template_id
    }
    target_template = templates.get(template_id)
    new_section_payloads = []
    for section in original.sections.all():
        template = section.template
        if template_id and template and template.id == template_id and target_template:
            window = (original.window_start, original.window_end)
            section_payloads = build_section_payloads(new_run, [target_template], window, section.review_text)
            if section_payloads:
                new_section_payloads.extend(section_payloads)
            continue

        stories_payloads = []
        for story in section.stories.all():
            articles = [item.article for item in story.story_articles.all()]
            stories_payloads.append(
                {
                    "title": story.title,
                    "summary": story.summary,
                    "central_idea": story.central_idea,
                    "labels_json": story.labels_json,
                    "signals": story.group_signals_json,
                    "article_count": story.article_count,
                    "unique_sources_count": story.unique_sources_count,
                    "source_names": story.source_names_json,
                    "type_counts": story.type_counts_json,
                    "sentiment_counts": story.sentiment_counts_json,
                    "group_label": story.group_label,
                    "articles": articles,
                    "story_fingerprint": story.story_fingerprint,
                }
            )
        if stories_payloads:
            new_section_payloads.append(
                {
                    "template": template,
                    "title": section.title,
                    "order": section.order,
                    "group_by": section.group_by,
                    "prompt_snapshot": section.prompt_snapshot,
                    "review_text": section.review_text,
                    "stories": stories_payloads,
                }
            )

    with transaction.atomic():
        persist_run(new_run, new_section_payloads)
        new_run.html_snapshot = render_run_to_html_snapshot(new_run.id)
        new_run.status = "completed"
        new_run.finished_at = timezone.now()
        new_run.save(update_fields=["html_snapshot", "status", "finished_at"])
    return new_run.id


@shared_task
def generate_pdf(run_id: int):
    return generate_pdf_service(run_id)
