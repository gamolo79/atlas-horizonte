import json
import logging
import os
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from monitor.linking import (
    extract_mentions,
    extract_mentions_ai,
    link_mentions,
    STATUS_THRESHOLDS,
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
             self.stdout.write(f"Using scope: {len(scope.get('personas',[]))} personas, {len(scope.get('instituciones',[]))} institutions")

        ai_client = None
        require_ai = False
        if not skip_ai_verify:
            if not os.environ.get("OPENAI_API_KEY"):
                self.stdout.write(self.style.WARNING("OPENAI_API_KEY no está configurada. Se omite verificación IA."))
            else:
                try:
                    from openai import OpenAI
                    ai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=15)
                    require_ai = True
                except ImportError:
                    self.stdout.write(self.style.WARNING("Paquete openai no disponible. Se omite verificación IA."))

        if rebuild and not dry_run:
            self.stdout.write("Purging existing links (rebuild=True)...")
            with transaction.atomic():
                self._purge_links(articles)

        # 1. Ensure mentions exist
        self.stdout.write("Extracting mentions...")
        with transaction.atomic():
            for i, article in enumerate(articles, 1):
                if not Mention.objects.filter(article=article).exists():
                     extract_mentions(article)
                if i % 100 == 0:
                     self.stdout.write(f"  Extracted mentions for {i}/{total_articles} articles...")

        # 2. Link mentions
        self.stdout.write("Linking mentions...")
        
        all_mentions = Mention.objects.filter(
            article__in=articles,
            entity_kind__in=[Mention.EntityKind.PERSON, Mention.EntityKind.ORG],
        ).select_related("article")
        
        count_mentions = all_mentions.count()
        self.stdout.write(f"Processing {count_mentions} mentions...")

        if count_mentions == 0:
             self.stdout.write(self.style.SUCCESS("No mentions found to link."))
             return

        totals, ai_error = link_mentions(
            all_mentions,
            scope=scope,
            ai_client=ai_client,
            ai_model=ai_model,
            ai_threshold=ai_threshold,
            require_ai_validation=require_ai,
            dry_run=dry_run
        )
        
        if ai_error:
             self.stdout.write(self.style.ERROR("Encountered AI errors during validation."))

        self.stdout.write(
            self.style.SUCCESS(
                "Done.\n"
                f"Articles: {totals['mentions_analyzed']} mentions processed\n"
                f"Links created: {totals['links_created']}\n"
                f"Links updated: {totals['links_updated']}\n"
                f"Proposed: {totals['proposed']}\n"
                f"AI rejected: {totals['ai_rejected']}\n"
                f"Ambiguous/low: {totals['ambiguous']}\n"
                f"No candidates: {totals['no_candidates']}"
            )
        )

    def _purge_links(self, articles):
        article_ids = [article.id for article in articles]
        ArticleEntity.objects.filter(article_id__in=article_ids).delete()
        EntityLink.objects.filter(mention__article_id__in=article_ids).delete()
        
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
