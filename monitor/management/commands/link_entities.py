import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from monitor.linking import (
    choose_winner,
    extract_mentions,
    persist_link,
    retrieve_candidates,
    score_candidates,
)
from monitor.models import Article, EntityLink, Mention, ArticleEntity, DigestClientConfig

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

    def handle(self, *args, **options):
        since = parse_since(options["since"])
        limit = options["limit"]
        dry_run = options["dry_run"]
        rebuild = options["rebuild"]
        client_id = options["client"]

        since_dt = timezone.now() - since
        articles = list(
            Article.objects.filter(published_at__gte=since_dt)
            .order_by("-published_at", "-id")[:limit]
        )

        scope = self._load_scope(client_id)

        totals = {
            "articles_processed": 0,
            "mentions_analyzed": 0,
            "links_created": 0,
            "links_updated": 0,
            "proposed": 0,
            "ambiguous": 0,
            "no_candidates": 0,
        }

        if rebuild and not dry_run:
            with transaction.atomic():
                self._purge_links(articles)

        for article in articles:
            totals["articles_processed"] += 1
            if not Mention.objects.filter(article=article).exists():
                extract_mentions(article)

            mentions = Mention.objects.filter(
                article=article,
                entity_kind__in=[Mention.EntityKind.PERSON, Mention.EntityKind.ORG],
            )
            for mention in mentions:
                totals["mentions_analyzed"] += 1
                candidates = retrieve_candidates(mention, scope=scope)
                if not candidates:
                    totals["no_candidates"] += 1
                    continue
                scored = score_candidates(mention, candidates)
                winner = choose_winner(scored)
                if not winner:
                    totals["ambiguous"] += 1
                    continue
                link, action = persist_link(mention, winner, dry_run=dry_run)
                if not link:
                    continue
                if link.status == EntityLink.Status.PROPOSED:
                    totals["proposed"] += 1
                elif action == "updated":
                    totals["links_updated"] += 1
                elif action == "created":
                    totals["links_created"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"Articles: {totals['articles_processed']} · "
                f"Mentions: {totals['mentions_analyzed']} · "
                f"Links created: {totals['links_created']} · "
                f"Links updated: {totals['links_updated']} · "
                f"Proposed: {totals['proposed']} · "
                f"Ambiguous/low: {totals['ambiguous']} · "
                f"No candidates: {totals['no_candidates']}"
            )
        )

    def _purge_links(self, articles):
        article_ids = [article.id for article in articles]
        EntityLink.objects.filter(mention__article_id__in=article_ids).delete()
        ArticleEntity.objects.filter(article_id__in=article_ids).delete()

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
