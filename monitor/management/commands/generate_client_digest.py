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
    if not s:
        return s
    prev = None
    cur = s
    for _ in range(5):
        if cur == prev:
            break
        prev = cur
        cur = html_unescape(cur)
    return cur

class Command(BaseCommand):
    help = "Generate a client-specific digest with 3-level hierarchy: Entities -> Topics -> General."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="YYYY-MM-DD (default: today)")
        parser.add_argument("--title", type=str, default="Síntesis diaria (cliente)")
        # Increased default to 15 to capture more context
        parser.add_argument("--top", type=int, default=15, help="Items per section")
        parser.add_argument("--hours", type=int, default=24)
        
        parser.add_argument("--person-id", type=int, action="append", default=[])
        parser.add_argument("--institution-id", type=int, action="append", default=[])
        parser.add_argument("--topics", type=str, help="Comma-separated topics", default="")

    def handle(self, *args, **opts):
        title = opts["title"]
        top_n = opts["top"]
        hours = opts["hours"]
        person_ids = set(opts["person_id"])
        institution_ids = set(opts["institution_id"])
        
        raw_topics = opts.get("topics", "") or ""
        topics_list = [t.strip().lower() for t in raw_topics.split(",") if t.strip()]

        # Date setup
        target_date_str = opts["date"]
        if target_date_str:
            y, m, d = map(int, target_date_str.split("-"))
            target_date = date_cls(y, m, d)
        else:
            target_date = date_cls.today()

        since = timezone.now() - timezone.timedelta(hours=hours)
        
        # We fetch clusters created in window
        all_clusters = StoryCluster.objects.filter(
            created_at__gte=since
        ).prefetch_related("mentions", "mentions__media_outlet", "mentions__article")
        
        clusters = list(all_clusters)
        self.stdout.write(f"Clusters candidate pool: {len(clusters)} (since {since})")
        
        if not clusters:
            self.stdout.write(self.style.WARNING("No recent clusters found."))
            return

        # --- SEPARATION LOGIC ---
        priority_clusters = []
        topic_clusters = []
        general_clusters = []
        
        seen_ids = set()

        for cluster in clusters:
            # Check Level 1: Entities
            has_person = cluster.mentions.filter(article__person_mentions__persona_id__in=person_ids).exists() if person_ids else False
            has_inst = cluster.mentions.filter(article__institution_mentions__institucion_id__in=institution_ids).exists() if institution_ids else False
            
            if has_person or has_inst:
                priority_clusters.append(cluster)
                seen_ids.add(cluster.id)
                continue

            # Check Level 2: Topics
            is_topic = False
            if topics_list:
                text_blob = (cluster.headline + " " + cluster.topic_label).lower()
                for t in cluster.topic_summary:
                    text_blob += " " + str(t.get("label", "")).lower()
                
                for keyword in topics_list:
                    if keyword in text_blob:
                        is_topic = True
                        break
            
            if is_topic:
                topic_clusters.append(cluster)
                seen_ids.add(cluster.id)
                continue
            
            # Level 3: General
            general_clusters.append(cluster)

        # Sort by volume (mentions count)
        priority_clusters.sort(key=lambda c: c.mentions.count(), reverse=True)
        topic_clusters.sort(key=lambda c: c.mentions.count(), reverse=True)
        general_clusters.sort(key=lambda c: c.mentions.count(), reverse=True)
        
        # Limit
        priority_clusters = priority_clusters[:top_n]
        topic_clusters = topic_clusters[:top_n]
        
        # For General, we might want MORE than top_n if priority/topic sections are empty
        # If we have very few priority items, expand general?
        effective_general_limit = top_n
        if len(priority_clusters) + len(topic_clusters) < 5:
            effective_general_limit = max(top_n, 20) # Ensure at least 20 items total if sections are distinct
        
        general_clusters = general_clusters[:effective_general_limit]
        
        with transaction.atomic():
            digest, _ = Digest.objects.update_or_create(
                title=title,
                date=target_date,
                defaults={"html_content": "", "json_content": {}},
            )
            
            digest.sections.all().delete()
            
            sections_data = []
            
            # 1. PRIORITY SECTION
            if priority_clusters:
                sec = DigestSection.objects.create(
                    digest=digest, label="Enfoque / Prioridad", order=1, 
                    section_type=DigestSection.SectionType.PRIORITY
                )
                self._add_items(sec, priority_clusters, sections_data)

            # 2. TOPIC SECTION
            if topic_clusters:
                sec = DigestSection.objects.create(
                    digest=digest, label="Temas de Interés", order=2,
                    section_type=DigestSection.SectionType.BY_TOPIC
                )
                self._add_items(sec, topic_clusters, sections_data)
                
            # 3. GENERAL SECTION
            if general_clusters:
                sec = DigestSection.objects.create(
                    digest=digest, label="Contexto General", order=3,
                    section_type=DigestSection.SectionType.GENERAL
                )
                self._add_items(sec, general_clusters, sections_data)
            
            # Build HTML
            html = self._build_html(title, target_date, sections_data)
            digest.html_content = html
            
            digest_json = {
                "title": title,
                "date": str(target_date),
                "sections": sections_data
            }
            digest.json_content = digest_json
            digest.save()
            
        self.stdout.write(self.style.SUCCESS(f"Digest generated: {len(priority_clusters)} priority, {len(topic_clusters)} topics, {len(general_clusters)} general."))

    def _add_items(self, section, clusters, sections_data_list):
        items_data = []
        for i, cluster in enumerate(clusters, 1):
            DigestItem.objects.create(section=section, cluster=cluster, order=i)
            
            vol = cluster.mentions.count()
            mentions_qs = cluster.mentions.select_related("media_outlet", "article").all()
            
            chips = []
            seen_media = set()
            for m in mentions_qs:
                mo_name = m.media_outlet.name
                if mo_name not in seen_media:
                    chips.append({"media": mo_name, "url": m.article.url})
                    seen_media.add(mo_name)
                    if len(chips) >= 5: break
            
            items_data.append({
                "cluster_id": cluster.id,
                "headline": cluster.headline,
                "lead": cluster.lead,
                "volume": vol,
                "chips": chips
            })
            
        sections_data_list.append({
            "label": section.label,
            "type": section.section_type,
            "items": items_data
        })

    def _build_html(self, title, date_obj, sections):
        html = []
        html.append(f"<h1>{escape(title)}</h1>")
        html.append(f"<p style='color: #666;'>Fecha: {date_obj}</p>")
        
        for sec in sections:
            html.append(f"<h2 style='margin-top: 25px; border-bottom: 2px solid #000; padding_bottom: 5px;'>{escape(sec['label'])}</h2>")
            for item in sec['items']:
                # Improve formatting
                html.append("<div style='margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid #eee;'>")
                html.append(f"<h3 style='margin-bottom: 5px; color: #111;'>{escape(item['headline'])}</h3>")
                if item['lead']:
                    html.append(f"<p style='margin-top: 5px; color: #444;'>{escape(item['lead'])}</p>")
                
                html.append("<div style='margin-top: 8px;'>")
                html.append(f"<span style='font-size: 0.85em; font-weight: bold; background: #eee; padding: 2px 6px; border-radius: 4px; margin-right: 10px;'>Cobertura: {item['volume']} fuentes</span>")
                
                for chip in item['chips']:
                    html.append(f"<a href='{chip['url']}' target='_blank' style='text-decoration: none; color: #0066cc; margin-right: 8px; font-size: 0.85em;'>[{chip['media']}]</a>")
                html.append("</div>")
                html.append("</div>")
        return "\n".join(html)
