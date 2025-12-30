from __future__ import annotations

import contextlib
import io
import re
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from monitor.models import Article, IngestRun, StoryCluster, StoryMention


def _normalize_title(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", (value or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class Command(BaseCommand):
    help = "Cluster recent articles using a normalized title key"

    def handle(self, *args, **options):
        run = IngestRun.objects.create(action="cluster_articles_simple", status=IngestRun.Status.RUNNING)
        buffer = io.StringIO()
        stats_seen = 0
        stats_new = 0
        stats_errors = 0

        try:
            with contextlib.redirect_stdout(buffer):
                window_start = timezone.now() - timedelta(hours=48)
                articles = Article.objects.filter(
                    Q(published_at__gte=window_start) | Q(published_at__isnull=True, fetched_at__gte=window_start)
                ).order_by("published_at", "id")
                print(f"Articulos en ventana: {articles.count()}")

                grouped = {}
                for article in articles:
                    stats_seen += 1
                    key = _normalize_title(article.title) or f"article-{article.id}"
                    grouped.setdefault(key, []).append(article)

                for key, group in grouped.items():
                    base_article = group[0]
                    cluster = StoryCluster.objects.create(
                        run=run,
                        cluster_key=key[:200],
                        headline=base_article.title,
                        lead=base_article.lead,
                        base_article=base_article,
                        confidence=min(1.0, len(group) / 5.0),
                    )
                    stats_new += 1

                    for article in group:
                        outlet = article.outlet
                        if outlet is None and article.source_id:
                            outlet = article.source.media_outlet
                        if outlet is None:
                            stats_errors += 1
                            print(f"Sin outlet para article {article.id}")
                            continue
                        StoryMention.objects.get_or_create(
                            cluster=cluster,
                            article=article,
                            defaults={
                                "media_outlet": outlet,
                                "match_score": 1.0,
                                "is_base_candidate": article.id == base_article.id,
                            },
                        )

                print(f"Clusters creados: {stats_new} errores: {stats_errors}")

            run.stats_seen = stats_seen
            run.stats_new = stats_new
            run.stats_errors = stats_errors
            run.log_text = buffer.getvalue()
            run.status = IngestRun.Status.SUCCESS
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "stats_seen",
                    "stats_new",
                    "stats_errors",
                    "log_text",
                    "status",
                    "finished_at",
                ]
            )
        except Exception as exc:
            run.stats_seen = stats_seen
            run.stats_new = stats_new
            run.stats_errors = stats_errors + 1
            run.log_text = buffer.getvalue()
            run.error_text = str(exc)
            run.status = IngestRun.Status.FAILED
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "stats_seen",
                    "stats_new",
                    "stats_errors",
                    "log_text",
                    "error_text",
                    "status",
                    "finished_at",
                ]
            )
            raise
