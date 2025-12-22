from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Avg, Count, Q

from monitor.models import (
    MediaSource,
    Article,
    StoryCluster,
    ArticlePersonaMention,
    ArticleInstitucionMention,
    IngestRun,
    Digest,
    EntityLink,
)


class Command(BaseCommand):
    help = "Diagnostica la salud de los subsistemas (Fetch, Sentiment, Clustering, Ingest, Digest)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== REPORTE DE SALUD DEL SISTEMA ==="))
        now = timezone.now()
        yesterday = now - timedelta(hours=24)

        # 1. FETCH STATUS
        self.stdout.write(self.style.MIGRATE_LABEL("\n[1] FETCH STATUS"))
        
        # Sources activos con error
        failing_sources = MediaSource.objects.filter(is_active=True).exclude(last_error="").count()
        if failing_sources > 0:
            self.stdout.write(self.style.ERROR(f"  FAILED SOURCES (Active): {failing_sources}"))
            for src in MediaSource.objects.filter(is_active=True).exclude(last_error="")[:5]:
                 self.stdout.write(f"    - {src} (Error: {src.last_error[:50]}...)")
        else:
            self.stdout.write(self.style.SUCCESS("  ALL ACTIVE SOURCES OK"))

        # Artículos recientes
        articles_24h = Article.objects.filter(created_at__gte=yesterday).count()
        self.stdout.write(f"  ARTICLES (Last 24h): {articles_24h}")

        # Missing body text (si fetch_article_bodies falla o no corre)
        missing_body = Article.objects.filter(created_at__gte=yesterday, body_text="").count()
        if missing_body > 0:
            self.stdout.write(self.style.WARNING(f"  MISSING BODY TEXT (Last 24h): {missing_body} (Possible scrape failure)"))
        else:
            self.stdout.write(self.style.SUCCESS("  ALL RECENT ARTICLES HAVE BODY"))


        # 2. SENTIMENT STATUS
        self.stdout.write(self.style.MIGRATE_LABEL("\n[2] SENTIMENT STATUS"))
        
        # Menciones personas
        p_mentions_24h = ArticlePersonaMention.objects.filter(created_at__gte=yesterday).count()
        p_pending = ArticlePersonaMention.objects.filter(created_at__gte=yesterday, sentiment__isnull=True).count()
        
        # Menciones instituciones
        i_mentions_24h = ArticleInstitucionMention.objects.filter(created_at__gte=yesterday).count()
        i_pending = ArticleInstitucionMention.objects.filter(created_at__gte=yesterday, sentiment__isnull=True).count()
        
        total_pending = p_pending + i_pending
        self.stdout.write(f"  MENTIONS (Last 24h): P={p_mentions_24h} / I={i_mentions_24h}")
        
        if total_pending > 0:
             self.stdout.write(self.style.WARNING(f"  PENDING CLASSIFICATION (Last 24h): {total_pending}"))
        else:
             self.stdout.write(self.style.SUCCESS("  ALL CLASSIFIED"))

        linked_person_mentions = EntityLink.objects.filter(
            status=EntityLink.Status.LINKED,
            entity_type=EntityLink.EntityType.PERSON,
            mention__article__published_at__gte=yesterday,
        ).count()
        linked_institution_mentions = EntityLink.objects.filter(
            status=EntityLink.Status.LINKED,
            entity_type=EntityLink.EntityType.INSTITUTION,
            mention__article__published_at__gte=yesterday,
        ).count()

        person_delta = linked_person_mentions - p_mentions_24h
        institution_delta = linked_institution_mentions - i_mentions_24h

        if person_delta or institution_delta:
            self.stdout.write(
                self.style.WARNING(
                    "  LINK INTEGRITY MISMATCH (Last 24h): "
                    f"PERSONA delta={person_delta} / INSTITUCION delta={institution_delta}"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("  LINK INTEGRITY OK (Last 24h)"))


        # 3. CLUSTERING STATUS
        self.stdout.write(self.style.MIGRATE_LABEL("\n[3] CLUSTERING STATUS"))
        clusters_24h = StoryCluster.objects.filter(created_at__gte=yesterday).count()
        self.stdout.write(f"  CLUSTERS CREATED (Last 24h): {clusters_24h}")

        cluster_quality = StoryCluster.objects.filter(created_at__gte=yesterday).aggregate(
            avg_cohesion=Avg("cohesion_score"),
            low_cohesion=Count("id", filter=Q(cohesion_score__lt=0.45)),
        )
        avg_cohesion = cluster_quality.get("avg_cohesion") or 0.0
        low_cohesion = cluster_quality.get("low_cohesion") or 0
        self.stdout.write(f"  AVG COHESION (Last 24h): {avg_cohesion:.2f}")
        if low_cohesion > 0:
            self.stdout.write(self.style.WARNING(f"  LOW COHESION CLUSTERS: {low_cohesion}"))
        else:
            self.stdout.write(self.style.SUCCESS("  NO LOW-COHESION CLUSTERS"))
        
        # Artículos huérfanos (sin cluster)
        # Ojo: esto asume que todo artículo debería tener cluster, lo cual depende de la regla
        # Si usas StoryMention para linkear article->cluster:
        articles_with_cluster = Article.objects.filter(
            created_at__gte=yesterday, 
            storymention__isnull=False
        ).distinct().count()
        
        orphans = articles_24h - articles_with_cluster
        if orphans > 0:
            pct = (orphans / articles_24h * 100) if articles_24h else 0
            self.stdout.write(self.style.WARNING(f"  ORPHAN ARTICLES: {orphans} ({pct:.1f}%)"))
        else:
            self.stdout.write(self.style.SUCCESS("  ALL ARTICLES CLUSTERED"))


        # 4. INGEST STATUS
        self.stdout.write(self.style.MIGRATE_LABEL("\n[4] INGEST RUNS"))
        # Runs recientes
        recent_runs = IngestRun.objects.filter(time_window_start__gte=yesterday).order_by("-id")[:5]
        if not recent_runs:
             self.stdout.write(self.style.WARNING("  NO INGEST RUNS IN LAST 24H"))
        else:
            for run in recent_runs:
                status_color = self.style.SUCCESS if run.status == "success" else self.style.ERROR
                self.stdout.write(status_color(f"  Run {run.id} [{run.status}]: {run.stats_total_fetched} fetched"))


        # 5. DIGEST STATUS
        self.stdout.write(self.style.MIGRATE_LABEL("\n[5] DIGEST"))
        today_date = now.date()
        digest = Digest.objects.filter(date=today_date).first()
        
        if digest:
            self.stdout.write(self.style.SUCCESS(f"  DIGEST FOUND: {digest}"))
            sections_count = digest.sections.count()
            self.stdout.write(f"  SECTIONS: {sections_count}")
            has_html = bool(digest.html_content)
            has_json = bool(digest.json_content)
            
            if has_html and has_json:
                self.stdout.write(self.style.SUCCESS("  CONTENT: HTML OK / JSON OK"))
            else:
                self.stdout.write(self.style.ERROR(f"  CONTENT MISSING: HTML={has_html} JSON={has_json}"))
        else:
            self.stdout.write(self.style.ERROR(f"  NO DIGEST FOR TODAY ({today_date})"))

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== FIN DEL REPORTE ==="))
