import json
import logging
import os
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from openai import OpenAI

from monitor.linking import (
    choose_winner,
    extract_mentions,
    extract_mentions_ai,
    link_mentions,
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
        parser.add_argument("--skip-ai-verify", action="store_true")
        parser.add_argument("--ai-model", type=str, default="gpt-4o-mini")
        parser.add_argument("--ai-threshold", type=float, default=0.6)

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(f"[DEBUG] link_entities file: {__file__}"))
        self.stdout.write(self.style.WARNING(f"[DEBUG] monitor.linking file: {sys.modules.get('monitor.linking').__file__}"))
        self.stdout.write(self.style.WARNING(f"[DEBUG] sys.path[0]: {sys.path[0]}"))
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

        scope = self._load_scope(client_id)

        totals = {
            "articles_processed": 0,
            "mentions_analyzed": 0,
            "links_created": 0,
            "links_updated": 0,
            "proposed": 0,
            "ambiguous": 0,
            "no_candidates": 0,
            "ai_rejected": 0,
        }

        ai_client = None
        if not skip_ai_verify:
            if not os.environ.get("OPENAI_API_KEY"):
                self.stdout.write(self.style.WARNING("OPENAI_API_KEY no está configurada. Se omite verificación IA."))
            else:
                try:
                    from openai import OpenAI
                except ImportError:
                    self.stdout.write(self.style.WARNING("Paquete openai no disponible. Se omite verificación IA."))
                else:
                    ai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=15)

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
                if ai_client and not self._ai_verify(ai_client, ai_model, ai_threshold, mention, winner):
                    totals["ai_rejected"] += 1
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
                f"AI rejected: {totals['ai_rejected']} · "
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

    def _ai_verify(self, client, model, threshold, mention, winner):
        entity = winner["entity"]
        entity_label = getattr(entity, "nombre_completo", None) or getattr(entity, "nombre", "") or ""
        context = (mention.context_window or "").strip()
        if not context:
            return True
        payload = {
            "entity_label": entity_label,
            "entity_type": winner["entity_type"],
            "mention_surface": mention.surface,
            "context": context[:1200],
            "article_title": (mention.article.title or "")[:200],
        }
        prompt = (
            "Valida si la mención en el contexto se refiere a la entidad indicada. "
            "Responde SOLO JSON con llaves: is_match (true/false), confidence (0-1), reason."
            f"\n\nEntidad: {payload['entity_label']}"
            f"\nTipo: {payload['entity_type']}"
            f"\nMención detectada: {payload['mention_surface']}"
            f"\nTítulo: {payload['article_title']}"
            f"\nContexto: {payload['context']}"
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un validador de menciones. Responde SOLO JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Error OpenAI (link_entities): {exc}"))
            return True

        content = response.choices[0].message.content
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            self.stdout.write(self.style.WARNING("JSON inválido en verificación IA."))
            return True
        if not isinstance(result, dict):
            return True
        is_match = result.get("is_match")
        confidence = result.get("confidence", 0.0)
        if is_match is False or confidence < threshold:
            return False
        return True
