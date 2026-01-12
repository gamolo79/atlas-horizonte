import time
from typing import Iterable, List, Optional, Tuple

import feedparser
import requests
from bs4 import BeautifulSoup
try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - fallback for missing dependency
    date_parser = None
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone
from lxml import etree
from readability import Document

from monitor.models import Article, Classification, Mention, Source
from monitor.services import build_catalog, classify_article, match_mentions
from redpolitica.models import Institucion, Persona, Topic


DEFAULT_TIMEOUT = 15
MAX_SITEMAP_URLS = 200


def parse_published(value: Optional[str]):
    if not value:
        return None
    if date_parser is None:
        try:
            return timezone.datetime.fromisoformat(value)
        except ValueError:
            return None
    try:
        return date_parser.parse(value)
    except (ValueError, TypeError):
        return None


def extract_html_content(html: str) -> Tuple[str, Optional[str], Optional[str]]:
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = soup.get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)

    meta_desc = None
    meta_keywords = None
    soup = BeautifulSoup(html, "lxml")
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag and desc_tag.get("content"):
        meta_desc = desc_tag["content"].strip()
    keywords_tag = soup.find("meta", attrs={"name": "keywords"})
    if keywords_tag and keywords_tag.get("content"):
        meta_keywords = keywords_tag["content"].strip()
    return text, meta_desc, meta_keywords


def fetch_url_content(url: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    response = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "Monitor/1.0"})
    response.raise_for_status()
    html = response.text
    text, meta_desc, meta_keywords = extract_html_content(html)
    return html, text, meta_desc, meta_keywords


def parse_sitemap(xml_content: str, base_url: str) -> List[str]:
    try:
        tree = etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []

    namespace = tree.nsmap.get(None, "")
    def _tag(name: str) -> str:
        return f"{{{namespace}}}{name}" if namespace else name

    urls = []
    if tree.tag.endswith("sitemapindex"):
        for sitemap in tree.findall(_tag("sitemap")):
            loc = sitemap.findtext(_tag("loc"))
            if loc:
                urls.append(loc.strip())
    else:
        for url in tree.findall(_tag("url")):
            loc = url.findtext(_tag("loc"))
            if loc:
                urls.append(loc.strip())
    return urls


def crawl_sitemap(url: str, seen: Optional[set] = None, limit: int = MAX_SITEMAP_URLS) -> List[str]:
    seen = seen or set()
    if url in seen or len(seen) >= limit:
        return []
    seen.add(url)
    try:
        response = requests.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "Monitor/1.0"})
        response.raise_for_status()
    except requests.RequestException:
        return []

    urls = parse_sitemap(response.text, url)
    if not urls:
        return []

    nested = []
    for link in urls:
        if link.endswith(".xml"):
            nested.extend(crawl_sitemap(link, seen=seen, limit=limit))
        else:
            nested.append(link)
        if len(nested) >= limit:
            break
    return nested[:limit]


class Command(BaseCommand):
    help = "Ingesta fuentes activas (RSS, sitemap o scrape)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Límite de artículos nuevos a crear")
        parser.add_argument("--limit-sources", type=int, default=None, help="Límite de fuentes a procesar")
        parser.add_argument("--source-id", type=int, help="Procesar una sola fuente")

    def handle(self, *args, **options):
        limit = options["limit"]
        source_id = options.get("source_id")
        limit_sources = options.get("limit_sources")

        personas = Persona.objects.all()
        instituciones = Institucion.objects.all()
        temas = Topic.objects.all()
        catalog = build_catalog(personas, instituciones, temas)

        sources = Source.objects.filter(is_active=True)
        if source_id:
            sources = sources.filter(id=source_id)
        if limit_sources:
            sources = sources[:limit_sources]

        total_new = 0
        for source in sources:
            if total_new >= limit:
                break
            start = time.monotonic()
            seen = 0
            created = 0
            errors = 0
            last_error = ""

            try:
                if source.source_type == "rss":
                    seen, created, errors, last_error = self._process_rss(
                        source,
                        limit - total_new,
                        catalog,
                    )
                elif source.source_type == "sitemap":
                    seen, created, errors, last_error = self._process_sitemap(
                        source,
                        limit - total_new,
                        catalog,
                    )
                elif source.source_type == "scrape":
                    seen, created, errors, last_error = self._process_scrape(
                        source,
                        limit - total_new,
                        catalog,
                    )
                else:
                    last_error = f"Tipo desconocido: {source.source_type}"
                    errors += 1
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                errors += 1

            elapsed_ms = int((time.monotonic() - start) * 1000)
            source.last_run_at = timezone.now()
            source.last_latency_ms = elapsed_ms
            source.last_new_count = created
            if errors:
                source.last_status = "error"
                source.last_error_text = last_error[:1000]
            else:
                source.last_status = "ok"
                source.last_ok_at = timezone.now()
                source.last_error_text = ""
            source.save(update_fields=[
                "last_run_at",
                "last_latency_ms",
                "last_new_count",
                "last_status",
                "last_error_text",
                "last_ok_at",
            ])

            total_new += created
            self.stdout.write(
                f"Fuente {source.name}: vistos={seen}, nuevos={created}, errores={errors}"
            )

        self.stdout.write(self.style.SUCCESS(f"Total nuevos: {total_new}"))

    def _process_rss(self, source: Source, limit: int, catalog) -> Tuple[int, int, int, str]:
        feed = feedparser.parse(source.url)
        seen = 0
        created = 0
        errors = 0
        last_error = ""

        for entry in feed.entries:
            if created >= limit:
                break
            seen += 1
            url = entry.get("link") or entry.get("id")
            if not url:
                continue
            published_at = parse_published(entry.get("published") or entry.get("updated"))
            title = entry.get("title") or "Sin título"
            author = entry.get("author") or ""
            content_text = ""
            if entry.get("summary"):
                content_text = BeautifulSoup(entry.get("summary"), "lxml").get_text(" ", strip=True)
            if entry.get("content"):
                content_text = BeautifulSoup(entry["content"][0].get("value", ""), "lxml").get_text(
                    " ", strip=True
                )

            raw_html = ""
            meta_desc = ""
            meta_keywords = ""
            if not content_text:
                try:
                    raw_html, content_text, meta_desc, meta_keywords = fetch_url_content(url)
                except requests.RequestException as exc:
                    errors += 1
                    last_error = str(exc)
                    continue

            try:
                article, created_flag = Article.objects.get_or_create(
                    url=url,
                    defaults={
                        "source": source,
                        "title": title,
                        "published_at": published_at,
                        "author": author,
                        "raw_html": raw_html,
                        "text": content_text,
                        "meta_description": meta_desc or "",
                        "meta_keywords": meta_keywords or "",
                    },
                )
            except IntegrityError:
                continue

            if created_flag:
                created += 1
                classify_error = self._classify_article(article, catalog)
                if classify_error:
                    errors += 1
                    last_error = classify_error
        return seen, created, errors, last_error

    def _process_sitemap(self, source: Source, limit: int, catalog) -> Tuple[int, int, int, str]:
        urls = crawl_sitemap(source.url)
        seen = 0
        created = 0
        errors = 0
        last_error = ""

        for url in urls:
            if created >= limit:
                break
            seen += 1
            try:
                raw_html, text, meta_desc, meta_keywords = fetch_url_content(url)
                title = "Sin título"
                soup = BeautifulSoup(raw_html, "lxml")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                article, created_flag = Article.objects.get_or_create(
                    url=url,
                    defaults={
                        "source": source,
                        "title": title,
                        "text": text,
                        "raw_html": raw_html,
                        "meta_description": meta_desc or "",
                        "meta_keywords": meta_keywords or "",
                    },
                )
                if created_flag:
                    created += 1
                    classify_error = self._classify_article(article, catalog)
                    if classify_error:
                        errors += 1
                        last_error = classify_error
            except requests.RequestException as exc:
                errors += 1
                last_error = str(exc)
            except IntegrityError:
                continue
        return seen, created, errors, last_error

    def _process_scrape(self, source: Source, limit: int, catalog) -> Tuple[int, int, int, str]:
        seen = 0
        created = 0
        errors = 0
        last_error = ""

        try:
            raw_html, text, meta_desc, meta_keywords = fetch_url_content(source.url)
            seen += 1
            title = "Sin título"
            soup = BeautifulSoup(raw_html, "lxml")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            article, created_flag = Article.objects.get_or_create(
                url=source.url,
                defaults={
                    "source": source,
                    "title": title,
                    "text": text,
                    "raw_html": raw_html,
                    "meta_description": meta_desc or "",
                    "meta_keywords": meta_keywords or "",
                },
            )
            if created_flag:
                created += 1
                classify_error = self._classify_article(article, catalog)
                if classify_error:
                    errors += 1
                    last_error = classify_error
        except requests.RequestException as exc:
            errors += 1
            last_error = str(exc)
        except IntegrityError:
            pass
        return seen, created, errors, last_error

    def _classify_article(self, article: Article, catalog) -> str:
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
            return ""
        except Exception as exc:  # noqa: BLE001
            article.status = "error"
            article.error_text = str(exc)[:1000]
            article.save(update_fields=["status", "error_text"])
            return str(exc)
