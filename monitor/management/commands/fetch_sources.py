from __future__ import annotations

import contextlib
import io
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Article, IngestRun, MediaSource

try:
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    feedparser = None


def _safe_dt(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    except Exception:
        return None


def _fetch_content(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "atlas-monitor/1.0"})
    with urlopen(req, timeout=20) as response:
        return response.read()


def _parse_with_feedparser(content: bytes):
    parsed = feedparser.parse(content)
    entries = []
    for entry in parsed.entries:
        entries.append(
            {
                "title": (entry.get("title") or "").strip(),
                "link": (entry.get("link") or "").strip(),
                "published": entry.get("published") or entry.get("updated"),
            }
        )
    return entries


def _parse_with_elementtree(content: bytes):
    entries = []
    root = ElementTree.fromstring(content)
    for item in root.findall(".//item"):
        entries.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published": item.findtext("pubDate") or item.findtext("date"),
            }
        )
    for entry in root.findall(".//{*}entry"):
        link = ""
        for link_tag in entry.findall("{*}link"):
            rel = link_tag.attrib.get("rel", "alternate")
            if rel == "alternate":
                link = link_tag.attrib.get("href", "")
                break
        entries.append(
            {
                "title": (entry.findtext("{*}title") or "").strip(),
                "link": (link or "").strip(),
                "published": entry.findtext("{*}published") or entry.findtext("{*}updated"),
            }
        )
    return entries


def _parse_feed(content: bytes):
    if feedparser is not None:
        return _parse_with_feedparser(content)
    return _parse_with_elementtree(content)


class Command(BaseCommand):
    help = "Fetch RSS sources and store as Articles"

    def handle(self, *args, **options):
        run = IngestRun.objects.create(action="fetch_sources", status=IngestRun.Status.RUNNING)
        buffer = io.StringIO()
        stats_seen = 0
        stats_new = 0
        stats_errors = 0

        try:
            with contextlib.redirect_stdout(buffer):
                sources = MediaSource.objects.filter(is_active=True, source_type="rss")
                print(f"Sources activos: {sources.count()}")
                for source in sources:
                    print(f"Fetch: {source.media_outlet.name} · {source.url}")
                    try:
                        content = _fetch_content(source.url)
                        entries = _parse_feed(content)
                        source.last_fetched_at = timezone.now()
                        source.last_error = ""
                        source.save(update_fields=["last_fetched_at", "last_error"])
                    except Exception as exc:
                        stats_errors += 1
                        source.last_error = str(exc)
                        source.last_fetched_at = timezone.now()
                        source.save(update_fields=["last_fetched_at", "last_error"])
                        print(f"Error en {source.url}: {exc}")
                        continue

                    for entry in entries:
                        stats_seen += 1
                        link = (entry.get("link") or "").strip()
                        if not link:
                            continue
                        title = (entry.get("title") or "").strip() or link
                        published = _safe_dt(entry.get("published"))
                        article, created = Article.objects.get_or_create(
                            url=link,
                            defaults={
                                "source": source,
                                "outlet": source.media_outlet,
                                "title": title,
                                "published_at": published,
                                "lead": "",
                                "body": "",
                                "language": "",
                                "hash_dedupe": Article.compute_hash(link),
                            },
                        )
                        if created:
                            stats_new += 1
                        else:
                            dirty_fields = []
                            if article.source_id != source.id:
                                article.source = source
                                dirty_fields.append("source")
                            if article.outlet_id != source.media_outlet_id:
                                article.outlet = source.media_outlet
                                dirty_fields.append("outlet")
                            if dirty_fields:
                                article.save(update_fields=dirty_fields)

                print(f"Resumen: vistos={stats_seen} nuevos={stats_new} errores={stats_errors}")

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
