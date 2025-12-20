from __future__ import annotations

from datetime import date
from collections import defaultdict
import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.html import escape

from monitor.models import Digest, DigestItem, DigestSection, StoryCluster


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    # normaliza guiones “–” y similares
    s = s.replace("–", "-").replace("—", "-")
    return s


def _story_signature(headline: str, lead: str) -> str:
    """
    Firma editorial para deduplicar historias aunque sean clusters distintos.
    """
    h = _norm(headline)
    l = _norm(lead)[:180]
    return f"{h}||{l}"


def _count_sentiments(mentions):
    pos = neu = neg = 0
    total = 0
    for m in mentions:
        s = getattr(m.article, "sentiment", None)
        if not s:
            continue
        total += 1
        label = (getattr(s, "label", "") or "").lower()
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            neu += 1
    return pos, neu, neg, total


def _count_content_types(mentions):
    info = opinion = 0
    total = 0
    for m in mentions:
        c = getattr(m.article, "content_classification", None)
        if not c:
            continue
        total += 1
        label = (getattr(c, "label", "") or "").lower()
        if label in ("opinion", "opinión", "opinion_piece"):
            opinion += 1
        else:
            info += 1
    return info, opinion, total


def _dedupe_mentions_by_outlet(mentions):
    buckets = defaultdict(list)
    for m in mentions:
        buckets[m.media_outlet_id].append(m)

    result = []
    for outlet_id, ms in buckets.items():
        ms_sorted = sorted(
            ms,
            key=lambda x: (
                getattr(x.article, "published_at", None) is not None,
                getattr(x.article, "published_at", None),
                x.article_id,
            ),
            reverse=True,
        )
        first = ms_sorted[0]
        outlet_name = first.media_outlet.name
        url = first.article.url
        result.append(
            {
                "outlet": outlet_name,
                "count": len(ms),
                "url": url,
                "article_ids": [mm.article_id for mm in ms_sorted],
            }
        )

    result.sort(key=lambda x: (-x["count"], x["outlet"].lower()))
    return result


class Command(BaseCommand):
    help = "Generate daily HTML + JSON digest with editorial sections, volume, sentiment and clickable sources."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD (default: today)")
        parser.add_argument("--title", type=str, default="Síntesis diaria de prensa")
        parser.add_argument("--top", type=int, default=5, help="How many stories go to Priority section")

    def handle(self, *args, **opts):
        target_date_str = opts["date"]
        title = opts["title"]
        top_n = opts["top"]

        if target_date_str:
            y, m, d = map(int, target_date_str.split("-"))
            target_date = date(y, m, d)
        else:
            target_date = date.today()

        clusters = list(
            StoryCluster.objects.all()
            .order_by("-created_at")
            .prefetch_related(
                "mentions__media_outlet",
                "mentions__article",
                "mentions__article__sentiment",
                "mentions__article__content_classification",
            )
        )

        if not clusters:
            self.stdout.write(self.style.WARNING("No hay historias para generar síntesis."))
            return

        def volume(c):
            return c.mentions.count()

        clusters_sorted = sorted(clusters, key=volume, reverse=True)

        priority = clusters_sorted[:top_n]
        priority_ids = {c.id for c in priority}
        rest = [c for c in clusters_sorted[top_n:] if c.id not in priority_ids]

        with transaction.atomic():
            digest, _ = Digest.objects.update_or_create(
                date=target_date,
                title=title,
                defaults={"html_content": "", "json_content": {}},
            )

            digest.sections.all().delete()

            sec_priority = DigestSection.objects.create(
                digest=digest,
                section_type=DigestSection.SectionType.PRIORITY,
                label="Enfoque / Prioridad",
                order=1,
            )
            sec_general = DigestSection.objects.create(
                digest=digest,
                section_type=DigestSection.SectionType.GENERAL,
                label="Notas generales",
                order=2,
            )

            # Guardamos items, pero filtramos duplicados editoriales en general
            seen_signatures = set()

            for i, c in enumerate(priority, start=1):
                DigestItem.objects.create(section=sec_priority, cluster=c, order=i)
                sig = _story_signature(c.headline, getattr(c, "lead", "") or "")
                seen_signatures.add(sig)

            order_general = 1
            for c in rest:
                sig = _story_signature(c.headline, getattr(c, "lead", "") or "")
                if sig in seen_signatures:
                    continue
                DigestItem.objects.create(section=sec_general, cluster=c, order=order_general)
                order_general += 1

            # ---- HTML + JSON
            html = []
            html.append('<meta charset="utf-8">')
            html.append(f"<h1>{escape(title)}</h1>")
            html.append(f"<p><strong>Fecha:</strong> {target_date}</p>")

            digest_json = {"title": title, "date": str(target_date), "sections": []}

            for sec in digest.sections.all().order_by("order"):
                html.append(f"<h2>{escape(sec.label)}</h2>")

                sec_json = {"label": sec.label, "section_type": sec.section_type, "items": []}

                items = sec.items.select_related("cluster").order_by("order")
                for item in items:
                    cluster = item.cluster
                    headline = item.custom_headline or cluster.headline
                    lead = item.custom_lead or (cluster.lead or "")

                    mentions = list(cluster.mentions.select_related("media_outlet", "article").all())
                    vol = len(mentions)

                    pos, neu, neg, s_total = _count_sentiments(mentions)
                    info, opinion, c_total = _count_content_types(mentions)

                    outlets = _dedupe_mentions_by_outlet(mentions)

                    html.append("<hr>")
                    html.append(f"<h3>{escape(headline)}</h3>")
                    html.append(f"<p><strong>Volumen:</strong> {vol} {'nota' if vol == 1 else 'notas'}</p>")

                    if s_total > 0:
                        html.append(
                            f"<p><strong>Sentimiento:</strong> "
                            f"{pos} positivo · {neu} neutro · {neg} negativo (de {s_total})</p>"
                        )

                    if c_total > 0:
                        html.append(
                            f"<p><strong>Tipo de texto:</strong> "
                            f"{info} informativo · {opinion} opinión (de {c_total})</p>"
                        )

                    if lead:
                        html.append(f"<p>{escape(lead)}</p>")

                    html.append("<ul>")
                    for o in outlets:
                        label = f'{o["outlet"]}'
                        if o["count"] > 1:
                            label += f' ({o["count"]})'
                        html.append(
                            f'<li><a href="{escape(o["url"])}" target="_blank" rel="noopener noreferrer">'
                            f'{escape(label)}</a></li>'
                        )
                    html.append("</ul>")

                    sec_json["items"].append(
                        {
                            "cluster_id": cluster.id,
                            "headline": headline,
                            "lead": lead,
                            "volume": vol,
                            "sentiment": {"positive": pos, "neutral": neu, "negative": neg, "total": s_total},
                            "content_type": {"informative": info, "opinion": opinion, "total": c_total},
                            "outlets": outlets,
                        }
                    )

                digest_json["sections"].append(sec_json)

            digest.html_content = "\n".join(html)
            digest.json_content = digest_json
            digest.save(update_fields=["html_content", "json_content"])

        self.stdout.write(self.style.SUCCESS("Digest creado/actualizado correctamente (HTML + JSON)"))
