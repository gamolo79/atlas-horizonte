from datetime import date as date_cls

from django.core.management.base import BaseCommand
from django.utils.html import escape
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from html import unescape as html_unescape

from monitor.models import (
    Article,
    Digest, DigestSection, DigestItem,
    StoryCluster,
)


def normalize_html_text(s: str) -> str:
    """
    Convierte entidades HTML repetidas (ej. '&amp;#8230;' -> '…') de forma segura.
    Repite html_unescape hasta que el texto deje de cambiar.
    """
    if not s:
        return s
    prev = None
    cur = s
    # límite para evitar loops raros
    for _ in range(5):
        if cur == prev:
            break
        prev = cur
        cur = html_unescape(cur)
    return cur

class Command(BaseCommand):
    help = "Generate a client-specific digest filtered by person/institution mentions. Works with clusters or articles-only."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD (default: today)")
        parser.add_argument("--title", type=str, default="Síntesis diaria (cliente)")
        parser.add_argument("--top", type=int, default=5)
        parser.add_argument("--hours", type=int, default=48)
        parser.add_argument("--person-id", type=int, action="append", default=[])
        parser.add_argument("--institution-id", type=int, action="append", default=[])

    def handle(self, *args, **opts):
        title = opts["title"]
        top_n = opts["top"]
        hours = opts["hours"]
        person_ids = opts["person_id"]
        institution_ids = opts["institution_id"]

        # Fecha
        target_date_str = opts["date"]
        if target_date_str:
            y, m, d = map(int, target_date_str.split("-"))
            target_date = date_cls(y, m, d)
        else:
            target_date = date_cls.today()

        if not person_ids and not institution_ids:
            self.stdout.write(self.style.ERROR("Debes pasar --person-id y/o --institution-id"))
            return

        since = timezone.now() - timezone.timedelta(hours=hours)

        # 1) Artículos en ventana + menciones (en tu modelo: person_mentions / institution_mentions)
        q_mentions = Q()
        if person_ids:
            q_mentions |= Q(person_mentions__persona_id__in=person_ids)
        if institution_ids:
            q_mentions |= Q(institution_mentions__institucion_id__in=institution_ids)

        articles_qs = (
            Article.objects.filter(published_at__gte=since)
            .filter(q_mentions)
            .distinct()
            .order_by("-published_at", "-id")
        )

        articles = list(articles_qs)
        self.stdout.write(f"Artículos filtrados: {len(articles)} (últimas {hours}h)")

        if not articles:
            self.stdout.write(self.style.WARNING("No hay artículos con esas menciones en la ventana."))
            return

        # 2) Intentar armar digest por clusters (StoryCluster) usando StoryMention reverse: storymention_set
        #    Relación: StoryMention(article -> Article, cluster -> StoryCluster)
        cluster_ids = set()
        allowed_article_ids = {article.id for article in articles}
        for a in articles:
            sm = a.storymention_set.select_related("cluster").first()
            if sm and sm.cluster_id:
                cluster_ids.add(sm.cluster_id)

        clusters = list(
            StoryCluster.objects.filter(id__in=list(cluster_ids)).order_by("-created_at", "-id")
        )

        with transaction.atomic():
            # upsert Digest por title+date (ajusta si tu Digest usa otra constraint)
            digest, _ = Digest.objects.get_or_create(
                title=title,
                date=target_date,
                defaults={"html_content": "", "json_content": {}},
            )

            # Limpia secciones/items previos para regenerar
            digest.sections.all().delete()

            html = []
            html.append(f"<h1>{escape(title)}</h1>")
            html.append(f"<p><strong>Fecha:</strong> {escape(target_date.isoformat())}</p>")
            html.append(f"<p><strong>Ventana:</strong> últimas {escape(str(hours))} horas</p>")

            digest_json = {
                "title": title,
                "date": target_date.isoformat(),
                "hours": hours,
                "mode": None,
                "filters": {"person_ids": person_ids, "institution_ids": institution_ids},
                "sections": [],
            }

            # ---- MODO CLUSTERS ----
            if clusters:
                digest_json["mode"] = "clusters"

                # Sección única (puedes expandir a más secciones luego)
                sec = DigestSection.objects.create(digest=digest, label="Enfoque / Prioridad", order=1)
                html.append("<h2>Enfoque / Prioridad</h2>")

                # Ordena clusters por volumen (mentions) desc y luego por recencia
                clusters_sorted = sorted(
                    clusters,
                    key=lambda c: (c.mentions.count(), c.created_at, c.id),
                    reverse=True
                )[:top_n]

                sec_json = {"label": sec.label, "items": []}

                for idx, cluster in enumerate(clusters_sorted, start=1):
                    DigestItem.objects.create(section=sec, cluster=cluster, order=idx)

                    headline = cluster.headline or ""
                    lead = cluster.lead or ""

                    # ✅ Arreglo: primero "unescape" para convertir &amp;#8230; -> &#8230; -> …
                    if lead:
                        lead = normalize_html_text(lead)

                    mentions_qs = cluster.mentions.select_related(
                        "media_outlet", "article"
                    ).filter(article_id__in=allowed_article_ids)
                    volume = mentions_qs.count()

                    html.append("<hr>")
                    html.append(f"<h3>{escape(headline)}</h3>")
                    html.append(f"<p><strong>Volumen:</strong> {volume} notas</p>")

                    if lead:
                        html.append(f"<p>{escape(lead)}</p>")

                    html.append("<div class='digest-chips'>")
                    chips = []
                    for mention in mentions_qs:
                        mo = mention.media_outlet.name if mention.media_outlet else "Medio"
                        url = mention.article.url if mention.article else ""
                        if url:
                            html.append(
                                f"<a class='digest-chip' href='{escape(url)}' target='_blank' rel='noopener noreferrer'>{escape(mo)}</a>"
                            )
                        else:
                            html.append(f"<span class='digest-chip'>{escape(mo)}</span>")

                        chips.append({"media_outlet": mo, "url": url})

                    html.append("</div>")

                    sec_json["items"].append({
                        "cluster_id": cluster.id,
                        "headline": headline,
                        "lead": lead,
                        "volume": volume,
                        "chips": chips,
                    })

                digest_json["sections"].append(sec_json)

            # ---- MODO ARTÍCULOS (SIN CLUSTERS) ----
            else:
                digest_json["mode"] = "articles_only"

                sec = DigestSection.objects.create(digest=digest, label="Enfoque / Prioridad", order=1)
                html.append("<h2>Enfoque / Prioridad</h2>")

                top_articles = articles[:top_n]
                sec_json = {"label": sec.label, "items": []}

                for idx, a in enumerate(top_articles, start=1):
                    DigestItem.objects.create(section=sec, article=a, order=idx)

                    headline = a.title or ""
                    lead = getattr(a, "lead", "") or ""

                    if lead:
                        lead = html_unescape(lead)

                    mo = a.media_outlet.name if a.media_outlet else "Medio"
                    url = a.url or ""
                    published = a.published_at.date().isoformat() if a.published_at else ""

                    html.append("<hr>")
                    if url:
                        html.append(
                            f"<h3><a href='{escape(url)}' target='_blank' rel='noopener noreferrer'>{escape(headline)}</a></h3>"
                        )
                    else:
                        html.append(f"<h3>{escape(headline)}</h3>")

                    html.append(f"<p><strong>Medio:</strong> {escape(mo)} &nbsp; <strong>Fecha:</strong> {escape(published)}</p>")

                    if lead:
                        html.append(f"<p>{escape(lead)}</p>")

                    sec_json["items"].append({
                        "article_id": a.id,
                        "headline": headline,
                        "lead": lead,
                        "media_outlet": mo,
                        "url": url,
                        "published_date": published,
                    })

                digest_json["sections"].append(sec_json)

            digest.html_content = "\n".join(html)
            digest.json_content = digest_json
            digest.save(update_fields=["html_content", "json_content"])

        self.stdout.write(self.style.SUCCESS(
            f"Digest de cliente creado/actualizado (modo {digest_json['mode']})."
        ))
