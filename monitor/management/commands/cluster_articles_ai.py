import hashlib
import os
import sys
import math
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import Count

from monitor.models import (
    Article,
    StoryCluster,
    StoryMention,
)

# Umbral estricto para evitar "bola de nieve"
DEFAULT_SIMILARITY_THRESHOLD = 0.76

def cosine(a, b):
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

class Command(BaseCommand):
    help = "Cluster articles using strict Leader-Based Incremental Clustering to prevent drift."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING("Starting Strict Leader-Based Clustering..."))
        
        hours = opts["hours"]
        limit = opts["limit"]
        threshold = opts["threshold"]
        dry = opts["dry_run"]

        since = timezone.now() - timezone.timedelta(hours=hours)

        # 1. Obtener artículos con embedding recientes
        articles = list(
            Article.objects.exclude(embedding=[])
            .filter(published_at__gte=since)
            .order_by("-published_at", "-id")[:limit]
        )

        if not articles:
            self.stdout.write(self.style.WARNING("No articles with embeddings found in window."))
            return

        # 2. Identificar cuáles ya están en un cluster (para no procesarlos de nuevo si no queremos, 
        #    o para validar. Lo estándar es ignorar los ya procesados para ser eficientes).
        existing_mentions_ids = set(
            StoryMention.objects.filter(article__in=articles).values_list("article_id", flat=True)
        )
        
        # Artículos "nuevos" que requieren asignación
        unclustered_articles = [a for a in articles if a.id not in existing_mentions_ids]
        
        if not unclustered_articles:
            self.stdout.write(self.style.SUCCESS("All articles in window are already clustered."))
            return

        self.stdout.write(f"Processing {len(unclustered_articles)} unclustered articles...")

        # 3. Cargar Clusters Activos (candidatos)
        #    "Leader-Based": Representamos el cluster por su artículo base (o su embedding original).
        #    Esto evita el "drift" del centroide promediado.
        active_clusters = []
        
        cluster_qs = (
            StoryCluster.objects.filter(created_at__gte=since)
            .select_related("base_article")
            .order_by("-created_at")
        )

        for cluster in cluster_qs:
            if not cluster.base_article or not cluster.base_article.embedding:
                continue
            active_clusters.append({
                "obj": cluster,
                "vector": cluster.base_article.embedding,
                "id": cluster.id,
                "headline": cluster.headline
            })

        created_clusters = 0
        joined_clusters = 0

        # 4. Loop Incremental
        with transaction.atomic():
            for article in unclustered_articles:
                vec = article.embedding
                if not vec: 
                    continue

                best_cluster = None
                best_score = -1.0

                # Comparar contra clusters existentes (y los nuevos creados en esta sesión)
                for c in active_clusters:
                    score = cosine(vec, c["vector"])
                    if score > best_score:
                        best_score = score
                        best_cluster = c

                # Decisión: Unir o Crear
                if best_score >= threshold:
                    # Unir a cluster existente
                    if not dry:
                        self._add_mention(best_cluster["obj"], article, score=best_score)
                    joined_clusters += 1
                    # Nota: NO actualizamos el vector del cluster (Leader-Based). 
                    # El cluster se queda anclado a su tema original.
                else:
                    # Crear nuevo cluster
                    created_clusters += 1
                    
                    if dry:
                        # En dry run simulamos la creación agregando a la lista en memoria
                        new_cluster_mock = {
                            "obj": None, # No DB obj
                            "vector": vec,
                            "id": f"new_{article.id}",
                            "headline": article.title
                        }
                        active_clusters.append(new_cluster_mock)
                    else:
                        new_cluster_obj = StoryCluster.objects.create(
                            headline=article.title,
                            lead=article.lead or "",
                            cluster_key=f"emb:{article.id}",
                            base_article=article,
                            topic_label="", # Se puede llenar luego con IA
                        )
                        self._add_mention(new_cluster_obj, article, score=1.0, is_base=True)
                        
                        # Agregamos a la lista de activos para que siguientes artículos puedan unirse a este
                        active_clusters.append({
                            "obj": new_cluster_obj,
                            "vector": vec,
                            "id": new_cluster_obj.id,
                            "headline": new_cluster_obj.headline
                        })

        if dry:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would create {created_clusters} clusters, join {joined_clusters}."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Created {created_clusters} new clusters. Joined {joined_clusters} articles to existing."))

    def _add_mention(self, cluster, article, score=0.0, is_base=False):
        mention, created = StoryMention.objects.get_or_create(
            cluster=cluster,
            article=article,
            defaults={
                "media_outlet": article.media_outlet,
                "match_score": score,
                "is_base_candidate": is_base,
            },
        )
        if not created:
            # Si ya existía (raro en este flujo, pero posible por reintentos), actualizamos score
            if mention.match_score != score:
                mention.match_score = score
                mention.save(update_fields=["match_score"])
