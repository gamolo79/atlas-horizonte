from django.core.management.base import BaseCommand

from monitor.models import Article, ArticleInstitucionMention, MonitorTopicMapping
from redpolitica.models import InstitutionTopic


class Command(BaseCommand):
    help = "Sincroniza los temas Atlas en artículos a partir de Article.topics."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        force = options["force"]
        dry_run = options["dry_run"]

        mappings = MonitorTopicMapping.objects.select_related("atlas_topic")
        mapping_by_label = {
            mapping.monitor_label.strip().lower(): mapping.atlas_topic_id
            for mapping in mappings
            if mapping.monitor_label
        }

        if not mapping_by_label:
            self.stdout.write(self.style.WARNING("No hay mapeos en MonitorTopicMapping."))

        qs = Article.objects.order_by("-id")
        if not force:
            qs = qs.filter(atlas_topics__isnull=True).distinct()
        if limit is not None:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Artículos a procesar: {total}")

        updated = 0
        skipped = 0

        for article in qs:
            topics = article.topics or []
            labels = []
            for entry in topics:
                if isinstance(entry, dict):
                    label = str(entry.get("label", "")).strip()
                elif isinstance(entry, str):
                    label = entry.strip()
                else:
                    continue
                if label:
                    labels.append(label)

            topic_ids = {
                mapping_by_label.get(label.lower())
                for label in labels
                if label
            }
            topic_ids.discard(None)

            institution_ids = list(
                ArticleInstitucionMention.objects.filter(article=article)
                .values_list("institucion_id", flat=True)
                .distinct()
            )
            if institution_ids:
                institution_topic_ids = InstitutionTopic.objects.filter(
                    institution_id__in=institution_ids
                ).values_list("topic_id", flat=True)
                topic_ids.update(institution_topic_ids)

            if not topic_ids:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"[DRY] article {article.id}: {len(topic_ids)} temas")
            else:
                article.atlas_topics.add(*topic_ids)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Procesados: {updated} · Sin cambios: {skipped} · Dry-run: {dry_run}"
            )
        )
