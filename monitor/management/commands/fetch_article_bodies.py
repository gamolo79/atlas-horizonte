import re
import requests

from bs4 import BeautifulSoup
from readability import Document

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Article


DISCLAIMER_PATTERNS = [
    r"suscr[íi]bete",
    r"newsletter",
    r"s[íi]guenos",
    r"seguir en",
    r"compartir",
    r"publicidad",
    r"pol[íi]tica de privacidad",
    r"t[ée]rminos y condiciones",
    r"contenido patrocinado",
    r"cookies",
]


def clean_text(txt: str) -> str:
    return re.sub(r"\s+", " ", txt).strip()


def strip_disclaimers(text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = []
    seen = set()
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        lower = sentence.lower()
        if any(re.search(pattern, lower) for pattern in DISCLAIMER_PATTERNS):
            continue
        if lower in seen:
            continue
        seen.add(lower)
        cleaned.append(sentence)
    return " ".join(cleaned).strip()


def normalize_body_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "aside", "nav"]):
        tag.decompose()
    text = clean_text(soup.get_text(" "))
    return strip_disclaimers(text)


def is_reliable_lead(lead: str) -> bool:
    return bool(lead and len(lead) >= 40)


def first_sentence(text: str) -> str:
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return sentence.strip()


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

                body_text = normalize_body_html(body_html)
                lead_text = clean_text(a.lead or "")
                if not is_reliable_lead(lead_text):
                    lead_text = first_sentence(body_text)
                lead_text = strip_disclaimers(lead_text)

                # guardrail para no meter cosas gigantes
                a.body_text = (body_text or "")[:50000]
                a.lead = (lead_text or "")[:2000]
                a.fetched_at = timezone.now()
                a.save(update_fields=["body_text", "lead", "fetched_at"])

                self.stdout.write(self.style.SUCCESS(f"OK {a.id} · {a.media_outlet.name}"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"FAIL {a.id} · {e}"))
