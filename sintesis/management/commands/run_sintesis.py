from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from atlas_core.text_utils import normalize_name
from monitor.models import Article
from sintesis.models import (
    SynthesisClient,
    SynthesisRun,
    SynthesisSchedule,
    SynthesisStory,
    SynthesisStoryArticle,
)
from sintesis.services import build_profile, generate_story_text, group_profiles


def _date_range(date_from, date_to):
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


def _client_interest_ids(client):
    personas = {client.persona_id} if client.persona_id else set()
    instituciones = {client.institucion_id} if client.institucion_id else set()
    temas = set()
    for interest in client.interests.all():
        if interest.persona_id:
            personas.add(interest.persona_id)
        if interest.institucion_id:
            instituciones.add(interest.institucion_id)
        if interest.topic_id:
            temas.add(interest.topic_id)
    return personas, instituciones, temas


def _keyword_tokens(client):
    keywords = client.keyword_tags or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]
    return {normalize_name(word) for word in keywords if word}


def _matches_client(article, client, keyword_tokens, personas, instituciones, temas):
    classification = getattr(article, "classification", None)
    if not classification:
        return False
    mentions = classification.mentions.all()
    for mention in mentions:
        if mention.target_type == "persona" and mention.target_id in personas:
            return True
        if mention.target_type == "institucion" and mention.target_id in instituciones:
            return True
        if mention.target_type == "tema" and mention.target_id in temas:
            return True
    if keyword_tokens:
        labels = [normalize_name(label) for label in classification.labels_json or []]
        text_blob = " ".join([classification.central_idea, article.title])
        text_blob = normalize_name(text_blob)
        for keyword in keyword_tokens:
            if keyword in labels or keyword in text_blob:
                return True
    return False


class Command(BaseCommand):
    help = "Genera síntesis agrupadas por cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, default=None)
        parser.add_argument("--schedule-id", type=int, default=None)
        parser.add_argument("--date-from", type=str, default=None)
        parser.add_argument("--date-to", type=str, default=None)

    def handle(self, *args, **options):
        schedule_id = options.get("schedule_id")
        client_id = options.get("client_id")
        date_from = options.get("date_from")
        date_to = options.get("date_to")

        date_from, date_to = self._parse_dates(date_from, date_to)

        clients = SynthesisClient.objects.filter(is_active=True)
        schedule = None
        run_type = "manual"
        if schedule_id:
            schedule = SynthesisSchedule.objects.select_related("client").get(pk=schedule_id)
            client_id = schedule.client_id
            run_type = "scheduled"
        if client_id:
            clients = clients.filter(pk=client_id)

        for client in clients:
            self.stdout.write(f"Generando síntesis para {client.name}...")
            run = SynthesisRun.objects.create(
                client=client,
                schedule=schedule,
                run_type=run_type,
                date_from=date_from,
                date_to=date_to,
                status="running",
            )
            try:
                count = self._process_client(client, run, date_from, date_to)
                run.status = "ok"
                run.output_count = count
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "output_count", "finished_at"])
            except Exception as exc:  # noqa: BLE001
                run.status = "error"
                run.log_text = str(exc)
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "log_text", "finished_at"])
                raise

    def _parse_dates(self, date_from, date_to):
        parsed_from = self._parse_date(date_from)
        parsed_to = self._parse_date(date_to)
        return _date_range(parsed_from, parsed_to)

    def _parse_date(self, value):
        if not value:
            return None
        try:
            return timezone.datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _process_client(self, client, run, date_from, date_to):
        personas, instituciones, temas = _client_interest_ids(client)
        keyword_tokens = _keyword_tokens(client)

        article_queryset = (
            Article.objects.select_related("source", "classification")
            .prefetch_related("classification__mentions")
            .order_by("-published_at", "-fetched_at")
        )

        article_queryset = _article_in_range(article_queryset, date_from, date_to)

        matching_articles = []
        for article in article_queryset:
            if _matches_client(article, client, keyword_tokens, personas, instituciones, temas):
                matching_articles.append(article)

        profiles = [build_profile(article) for article in matching_articles]
        groups = group_profiles(profiles)

        created = 0
        for group in groups:
            story_text = generate_story_text(group)
            profiles = group["profiles"]
            with transaction.atomic():
                story = SynthesisStory.objects.create(
                    client=client,
                    run=run,
                    title=story_text["title"],
                    summary=story_text["summary"],
                    central_idea=profiles[0].central_idea if profiles else "",
                    labels_json=list(group["labels"]),
                    article_count=len(profiles),
                    date_from=date_from,
                    date_to=date_to,
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
            created += 1
        return created
