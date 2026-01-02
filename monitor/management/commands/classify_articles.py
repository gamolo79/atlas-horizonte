from datetime import datetime
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from monitor.models import Article, Classification, Mention
from monitor.services import build_catalog, classify_article, match_mentions
from redpolitica.models import Institucion, Persona, Topic


class Command(BaseCommand):
    help = "Clasifica artículos con IA y genera menciones."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Límite de artículos a clasificar")
        parser.add_argument("--force", action="store_true", help="Reprocesar aunque exista clasificación")
        parser.add_argument("--date-from", dest="date_from", help="Fecha inicio YYYY-MM-DD")
        parser.add_argument("--date-to", dest="date_to", help="Fecha fin YYYY-MM-DD")

    def handle(self, *args, **options):
        limit = options["limit"]
        force = options["force"]
        date_from = self._parse_date(options.get("date_from"))
        date_to = self._parse_date(options.get("date_to"))

        personas = Persona.objects.all()
        instituciones = Institucion.objects.all()
        temas = Topic.objects.all()
        catalog = build_catalog(personas, instituciones, temas)

        queryset = Article.objects.all().order_by("-published_at", "-fetched_at")
        if date_from or date_to:
            queryset = self._apply_date_filter(queryset, date_from, date_to)

        if force:
            queryset = queryset
        else:
            queryset = queryset.filter(classification__isnull=True)

        processed = 0
        errors = 0
        for article in queryset[:limit]:
            try:
                classification = article.classification
            except ObjectDoesNotExist:
                classification = None
            if classification and classification.is_editor_locked:
                continue
            try:
                payload = classify_article(article, catalog)
                matches = match_mentions(payload.get("mentions", []), catalog)
                with transaction.atomic():
                    classification, created = Classification.objects.update_or_create(
                        article=article,
                        defaults={
                            "central_idea": payload["central_idea"],
                            "article_type": payload["article_type"],
                            "labels_json": payload["labels"],
                            "model_name": payload.get("_model_name", "unknown"),
                            "prompt_version": "v1",
                        },
                    )
                    if not created:
                        classification.mentions.all().delete()
                    Mention.objects.bulk_create(
                        [
                            Mention(classification=classification, **match)
                            for match in matches
                        ]
                    )
                    article.status = "processed"
                    article.error_text = ""
                    article.save(update_fields=["status", "error_text"])
                processed += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                article.status = "error"
                article.error_text = str(exc)[:1000]
                article.save(update_fields=["status", "error_text"])
                self.stderr.write(f"Error en artículo {article.id}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Clasificados: {processed}. Errores: {errors}"))

    def _parse_date(self, value: Optional[str]):
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _apply_date_filter(self, queryset, date_from, date_to):
        if date_from and date_to:
            return queryset.filter(
                Q(published_at__date__gte=date_from, published_at__date__lte=date_to)
                | Q(fetched_at__date__gte=date_from, fetched_at__date__lte=date_to)
            )
        if date_from:
            return queryset.filter(Q(published_at__date__gte=date_from) | Q(fetched_at__date__gte=date_from))
        if date_to:
            return queryset.filter(Q(published_at__date__lte=date_to) | Q(fetched_at__date__lte=date_to))
        return queryset
