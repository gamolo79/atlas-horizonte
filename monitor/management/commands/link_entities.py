import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from monitor.linking import link_mentions, sync_article_mentions_from_links, STATUS_THRESHOLDS
from monitor.models import (
    Article,
    EntityLink,
    ArticleEntity,
    ArticlePersonaMention,
    ArticleInstitucionMention,
    DigestClientConfig,
)

LOGGER = logging.getLogger(__name__)


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
    help = "Resolve mentions into Atlas entities with deterministic rules."

    def add_arguments(self, parser):
        parser.add_argument("--since", default="7d", help="Window, e.g. 7d or 24h.")
        parser.add_argument("--client", type=int, default=None, help="DigestClient id (optional).")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--rebuild", action="store_true")
        parser.add_argument("--skip-ai-verify", action="store_true")
        parser.add_argument("--ai-model", type=str, default="gpt-4o-mini")
        parser.add_argument("--ai-threshold", type=float, default=0.6)

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting link_entities command..."))

        since = parse_since(options["since"])
        limit = options["limit"]
        dry_run = options["dry_run"]
        rebuild = options["rebuild"]
        client_id = options["client"]
        skip_ai_verify = options["skip_ai_verify"]
        ai_model = options["ai_model"]
        ai_threshold = options["ai_threshold"]

        since_dt = timezone.now() - since
        articles = list(
            Article.objects.filter(published_at__gte=since_dt)
            .order_by("-published_at", "-id")[:limit]
        )
        
        total_articles = len(articles)
        self.stdout.write(f"Found {total_articles} articles since {since_dt}.")

        if total_articles == 0:
            self.stdout.write(self.style.WARNING("No articles found in window. Nothing to do."))
            return

        scope = self._load_scope(client_id)
        if scope:
            self.stdout.write(
                self.style.WARNING(
                    "Scope filtering is not supported in the current linker. Proceeding without scope."
                )
            )

        if rebuild and not dry_run:
            self.stdout.write("Purging existing links (rebuild=True)...")
            with transaction.atomic():
                self._purge_links(articles)

        # Link mentions
        self.stdout.write("Linking mentions...")

        thresholds = {**STATUS_THRESHOLDS, "proposed": ai_threshold}
        totals = link_mentions(
            articles,
            limit=limit,
            thresholds=thresholds,
            ai_model=ai_model,
            skip_ai_verify=skip_ai_verify,
        )

        sync_totals = sync_article_mentions_from_links(articles, dry_run=dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                "Done.\n"
                f"Articles processed: {totals['processed']}\n"
                f"Mentions created: {totals['mentions_created']}\n"
                f"Links created: {totals['links_created']}\n"
                f"Links updated: {totals['links_updated']}\n"
                f"Article entities synced: {sync_totals['article_entities_synced']}\n"
                f"Persona mentions created: {sync_totals['persona_mentions_created']}\n"
                f"Institucion mentions created: {sync_totals['institucion_mentions_created']}"
            )
        )

    def _purge_links(self, articles):
        article_ids = [article.id for article in articles]
        ArticleEntity.objects.filter(article_id__in=article_ids).delete()
        EntityLink.objects.filter(mention__article_id__in=article_ids).delete()
        ArticlePersonaMention.objects.filter(article_id__in=article_ids).delete()
        ArticleInstitucionMention.objects.filter(article_id__in=article_ids).delete()
        
    def _load_scope(self, client_id):
        if not client_id:
            return None
        try:
            config = DigestClientConfig.objects.select_related("client").get(client_id=client_id)
        except DigestClientConfig.DoesNotExist:
            LOGGER.warning("DigestClientConfig missing for client=%s", client_id)
            return None
        return {
            "personas": list(config.personas.values_list("id", flat=True)),
            "instituciones": list(config.instituciones.values_list("id", flat=True)),
        }
