from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Article, ArticleEntity, EntityLink, Mention
from redpolitica.models import Institucion, Persona


def parse_since(value):
    if isinstance(value, timedelta):
        return value
    text = (value or "").strip().lower()
    if not text:
        return timedelta(days=7)
    if text.endswith("d"):
        return timedelta(days=int(text[:-1]))
    if text.endswith("h"):
        return timedelta(hours=int(text[:-1]))
    return timedelta(days=int(text))


class Command(BaseCommand):
    help = "Compute entities_extracted for recent articles from links and mentions."

    def add_arguments(self, parser):
        parser.add_argument("--since", default="7d", help="Window, e.g. 7d or 24h.")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        since = parse_since(options["since"])
        limit = options["limit"]
        dry_run = options["dry_run"]

        since_dt = timezone.now() - since
        articles = list(
            Article.objects.filter(published_at__gte=since_dt)
            .order_by("-published_at", "-id")[:limit]
        )

        if not articles:
            self.stdout.write(self.style.WARNING("No recent articles found."))
            return

        updated = 0
        for article in articles:
            payload = self._build_payload(article.id)
            if payload != (article.entities_extracted or {}):
                updated += 1
                if not dry_run:
                    Article.objects.filter(id=article.id).update(entities_extracted=payload)

        status = "Dry run" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{status} {updated} articles."))

    def _build_payload(self, article_id):
        linked_mention_ids = set(
            EntityLink.objects.filter(
                mention__article_id=article_id,
                status=EntityLink.Status.LINKED,
            ).values_list("mention_id", flat=True)
        )

        entities = ArticleEntity.objects.filter(article_id=article_id)

        person_ids = list(
            entities.filter(entity_type=EntityLink.EntityType.PERSON).values_list(
                "entity_id", flat=True
            )
        )
        institution_ids = list(
            entities.filter(entity_type=EntityLink.EntityType.INSTITUTION).values_list(
                "entity_id", flat=True
            )
        )

        person_names = list(
            Persona.objects.filter(id__in=person_ids).values_list("nombre_completo", flat=True)
        )
        institution_names = list(
            Institucion.objects.filter(id__in=institution_ids).values_list("nombre", flat=True)
        )

        other_mentions = Mention.objects.filter(article_id=article_id)
        if linked_mention_ids:
            other_mentions = other_mentions.exclude(id__in=linked_mention_ids)
        other_surfaces = list(other_mentions.values_list("surface", flat=True))

        return {
            "PERSON": sorted({name.strip() for name in person_names if name and name.strip()}),
            "INSTITUTION": sorted(
                {name.strip() for name in institution_names if name and name.strip()}
            ),
            "OTHER": sorted({surface.strip() for surface in other_surfaces if surface and surface.strip()}),
        }
