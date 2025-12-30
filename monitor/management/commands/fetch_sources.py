import re
from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.utils import timezone

import feedparser

from monitor.models import Source, Article


TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
}

LEAD_DISCLAIMER_PATTERNS = [
    r"suscr[íi]bete",
    r"newsletter",
    r"s[íi]guenos",
    r"seguir en",
    r"compartir",
    r"publicidad",
    r"pol[íi]tica de privacidad",
    r"t[ée]rminos y condiciones",
]


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


def _is_tracking_param(key: str) -> bool:
    key = (key or "").lower()
    return key.startswith("utm_") or key in TRACKING_PARAMS


def _normalize_url(url: str) -> str:
    if not url:
        return url
    try:
        parts = urlsplit(url)
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking_param(k)
        ]
        query.sort()
        clean = parts._replace(query=urlencode(query, doseq=True), fragment="")
        return urlunsplit(clean)
    except Exception:
        return url


def _get_or_create_article(url, defaults):
    try:
        return Article.objects.get_or_create(url=url, defaults=defaults)
    except Article.MultipleObjectsReturned:
        return Article.objects.filter(url=url).first(), False
    except Exception:
        obj = Article.objects.filter(url=url).first()
        if obj:
            return obj, False
        raise


def _clean_lead(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    cleaned = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if any(re.search(pattern, lowered) for pattern in LEAD_DISCLAIMER_PATTERNS):
        return ""
    return cleaned


class Command(BaseCommand):
    help = "Fetch RSS sources and store as Articles (V1: title + lead/snippet)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Max items per source")
        parser.add_argument("--source-id", type=int, default=None, help="Fetch only one Source id")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        source_id = opts["source_id"]

        qs = Source.objects.filter(is_active=True, source_type="rss")
        if source_id:
            qs = qs.filter(id=source_id)

        total_new = 0
        total_seen = 0

        for src in qs:
            self.stdout.write(self.style.MIGRATE_HEADING(f"Fetching: {src.outlet} · {src.url}"))

            feed = feedparser.parse(src.url)

            src.last_fetched_at = timezone.now()
            src.last_error = ""
            src.save(update_fields=["last_fetched_at", "last_error"])

            entries = feed.entries[:limit]
            for e in entries:
                total_seen += 1
                raw_url = (e.get("link") or "").strip()
                url = _normalize_url(raw_url)
                if not url:
                    continue

                title = (e.get("title") or "").strip()
                # Muchos RSS traen summary; si no, deja vacío
                lead = _clean_lead(e.get("summary") or "")

                published = None
                # feedparser suele traer published/parsing
                if e.get("published"):
                    published = _safe_dt(e.get("published"))
                elif e.get("updated"):
                    published = _safe_dt(e.get("updated"))

                defaults = {
                    "source": src,
                    "title": title or url,
                    "lead": lead[:2000],  # recorta para evitar basura enorme
                    "published_at": published,
                    "language": "es",
                    "url": url,
                }

                obj, created = _get_or_create_article(url, defaults)

                if created:
                    total_new += 1

            self.stdout.write(self.style.SUCCESS(f"OK. Items vistos: {len(entries)} · Nuevos: {total_new}"))

        self.stdout.write(self.style.SUCCESS(f"Terminado. Vistos: {total_seen} · Nuevos: {total_new}"))
