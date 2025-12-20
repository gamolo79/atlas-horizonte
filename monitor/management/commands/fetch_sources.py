import hashlib
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

import feedparser

from monitor.models import MediaSource, Article


def _safe_dt(value):
    """Convierte fechas RSS comunes a datetime aware (UTC)."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt.astimezone(dt_timezone.utc)
    except Exception:
        return None


class Command(BaseCommand):
    help = "Fetch RSS sources and store as Articles (V1: title + lead/snippet)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Max items per source")
        parser.add_argument("--source-id", type=int, default=None, help="Fetch only one MediaSource id")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        source_id = opts["source_id"]

        qs = MediaSource.objects.filter(is_active=True, source_type="rss")
        if source_id:
            qs = qs.filter(id=source_id)

        total_new = 0
        total_seen = 0

        for src in qs.select_related("media_outlet"):
            self.stdout.write(self.style.MIGRATE_HEADING(f"Fetching: {src.media_outlet.name} · {src.url}"))

            feed = feedparser.parse(src.url)

            src.last_fetched_at = timezone.now()
            src.last_error = ""
            src.save(update_fields=["last_fetched_at", "last_error"])

            entries = feed.entries[:limit]
            for e in entries:
                total_seen += 1
                url = (e.get("link") or "").strip()
                if not url:
                    continue

                title = (e.get("title") or "").strip()
                # Muchos RSS traen summary; si no, deja vacío
                lead = (e.get("summary") or "").strip()

                published = None
                # feedparser suele traer published/parsing
                if e.get("published"):
                    published = _safe_dt(e.get("published"))
                elif e.get("updated"):
                    published = _safe_dt(e.get("updated"))

                # Dedup por URL (suficiente para V1)
                obj, created = Article.objects.get_or_create(
                    url=url,
                    defaults={
                        "media_outlet": src.media_outlet,
                        "source": src,
                        "title": title or url,
                        "lead": lead[:2000],  # recorta para evitar basura enorme
                        "published_at": published,
                        "language": "es",
                    },
                )
                if created:
                    total_new += 1

            self.stdout.write(self.style.SUCCESS(f"OK. Items vistos: {len(entries)} · Nuevos: {total_new}"))

        self.stdout.write(self.style.SUCCESS(f"Terminado. Vistos: {total_seen} · Nuevos: {total_new}"))
