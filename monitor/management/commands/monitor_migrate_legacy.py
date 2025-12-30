from django.core.management.base import BaseCommand
from django.db import connection, transaction

from monitor.models import Article, Source


class Command(BaseCommand):
    help = "Migra fuentes y artículos válidos desde tablas legadas."

    def handle(self, *args, **options):
        tables = set(connection.introspection.table_names())
        legacy_sources = "monitor_mediasource"
        legacy_articles = "monitor_article"
        migrated_sources = 0
        migrated_articles = 0

        if legacy_sources not in tables or legacy_articles not in tables:
            self.stdout.write(self.style.WARNING("No se encontraron tablas legadas para migrar."))
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, url, source_type, is_active, last_fetched_at FROM monitor_mediasource"
                )
                for row in cursor.fetchall():
                    legacy_id, url, source_type, is_active, last_fetched_at = row
                    source, created = Source.objects.get_or_create(
                        url=url,
                        defaults={
                            "name": f"Legacy {legacy_id}",
                            "outlet": "Legacy",
                            "source_type": source_type or Source.SourceType.HTML,
                            "is_active": is_active,
                            "last_fetched_at": last_fetched_at,
                        },
                    )
                    if created:
                        migrated_sources += 1

                cursor.execute(
                    "SELECT url, title, body_text, published_at, fetched_at, language FROM monitor_article"
                )
                for url, title, body_text, published_at, fetched_at, language in cursor.fetchall():
                    if not url or not title:
                        continue
                    body = body_text or ""
                    hash_dedupe = Article.compute_hash(url, url, body)
                    article, created = Article.objects.get_or_create(
                        url=url,
                        defaults={
                            "canonical_url": url,
                            "title": title,
                            "lead": "",
                            "body": body,
                            "published_at": published_at,
                            "fetched_at": fetched_at,
                            "outlet": "Legacy",
                            "language": language or "es",
                            "hash_dedupe": hash_dedupe,
                        },
                    )
                    if created:
                        migrated_articles += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Migradas {migrated_sources} fuentes y {migrated_articles} artículos."
            )
        )
