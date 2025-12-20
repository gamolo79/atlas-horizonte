import re
import requests

from bs4 import BeautifulSoup
from readability import Document

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Article


def clean_text(txt: str) -> str:
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


class Command(BaseCommand):
    help = "Fetch full article body from URL and store it in Article.body_text"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        force = opts["force"]

        qs = Article.objects.all().order_by("-published_at", "-id")
        if not force:
            qs = qs.filter(body_text="")

        qs = qs[:limit]
        self.stdout.write(f"Articles to fetch: {qs.count()}")

        for a in qs:
            try:
                r = requests.get(
                    a.url,
                    timeout=25,
                    headers={"User-Agent": "Mozilla/5.0 (MonitorHorizonte)"},
                )
                r.raise_for_status()

                doc = Document(r.text)
                body_html = doc.summary()

                soup = BeautifulSoup(body_html, "lxml")
                body_text = clean_text(soup.get_text(" "))

                # guardrail para no meter cosas gigantes
                a.body_text = (body_text or "")[:50000]
                a.fetched_at = timezone.now()
                a.save(update_fields=["body_text", "fetched_at"])

                self.stdout.write(self.style.SUCCESS(f"OK {a.id} · {a.media_outlet.name}"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"FAIL {a.id} · {e}"))
