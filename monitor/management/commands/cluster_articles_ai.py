import hashlib
import os
import sys
import math
from contextlib import nullcontext
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import Count

from monitor.aggregations import refresh_cluster_atlas_topics
from monitor.models import (
    Article,
    StoryCluster,
    StoryMention,
)

# Umbral más estricto por defecto
DEFAULT_SIMILARITY_THRESHOLD = 0.82

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
    help = "Cluster articles using strict Leader-Based Incremental Clustering with Entity & Topic Guards."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING("Starting Strict Leader-Based Clustering (Entity+Topic Guided)..."))
        
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

        # 2. Identificar cuáles ya están en un cluster
        existing_mentions_ids = set(
            StoryMention.objects.filter(article__in=articles).values_list("article_id", flat=True)
        )
        
        unclustered_articles = [a for a in articles if a.id not in existing_mentions_ids]
        
        if not unclustered_articles:
            self.stdout.write(self.style.SUCCESS("All articles in window are already clustered."))
            return

        self.stdout.write(f"Processing {len(unclustered_articles)} unclustered articles...")

        # 3. Cargar Clusters Activos (candidatos)
        # Leader-Based: Representamos cluster por ARTICLE BASE.
        active_clusters = []
        cluster_qs = (
            StoryCluster.objects.filter(created_at__gte=since)
            .select_related("base_article")
            .order_by("-created_at")
        )

        for cluster in cluster_qs:
            if not cluster.base_article or not cluster.base_article.embedding:
                continue
                
            # Pre-calc entities
            entities = set()
            ents_json = cluster.base_article.entities_extracted or {}
            for kind, names in ents_json.items():
                if isinstance(names, list):
                    for n in names:
                        entities.add(n.strip().lower())
            
            # Pre-calc Topics
            topics = set()
            tops_json = cluster.base_article.topics or []
            for t in tops_json:
                # Format: {"label": "X", "confidence": "media"} OR "label"
                lbl = t.get("label") if isinstance(t, dict) else t
                if lbl:
                    topics.add(lbl.strip().lower())

            active_clusters.append({
                "obj": cluster,
                "vector": cluster.base_article.embedding,
                "id": cluster.id,
                "headline": cluster.headline,
                "entities": entities,
                "topics": topics
            })

        created_clusters = 0
        joined_clusters = 0
        touched_clusters = set()

        # Optimization: Pre-calc meta for new articles
        processed_unclustered = []
        for a in unclustered_articles:
            entities = set()
            ents_json = a.entities_extracted or {}
            for kind, names in ents_json.items():
                if isinstance(names, list):
                    for n in names:
                        entities.add(n.strip().lower())
            
            topics = set()
            tops_json = a.topics or []
            for t in tops_json:
                lbl = t.get("label") if isinstance(t, dict) else t
                if lbl:
                    topics.add(lbl.strip().lower())

            processed_unclustered.append({"article": a, "entities": entities, "topics": topics})

        # 4. Loop Incremental
        transaction_ctx = transaction.atomic() if not dry else nullcontext()
        with transaction_ctx:
            for item in processed_unclustered:
                article = item["article"]
                a_entities = item["entities"]
                a_topics = item["topics"]
                vec = article.embedding
                
                best_cluster = None
                best_score = -1.0
                
                for c in active_clusters:
                    raw_score = cosine(vec, c["vector"])
                    final_score = raw_score
                    
                    # --- TOPIC GUARD ---
                    # If articles have topics but SHARE NONE -> Penalize
                    # Note: articles might lack topics if extraction failed. If so, ignore guard?
                    # Let's be strict: if BOTH have topics and overlap is empty -> penalize.
                    if a_topics and c["topics"]:
                        if not a_topics.intersection(c["topics"]):
                             # "Seguridad" vs "Obras" -> Penalize
                             final_score -= 0.15 
                    
                    # --- ENTITY GUARD ---
                    # If score is still high (borderline), enforce entity sync
                    if final_score >= threshold and final_score < 0.90:
                        if a_entities and c["entities"]:
                            if not a_entities.intersection(c["entities"]):
                                final_score -= 0.10
                    
                    if final_score > best_score:
                        best_score = final_score
                        best_cluster = c

                if best_score >= threshold:
                    # JOIN
                    if not dry:
                        cluster_obj = best_cluster["obj"]
                        self._add_mention(cluster_obj, article, score=best_score)
                        touched_clusters.add(cluster_obj.id)
                    joined_clusters += 1
                else:
                    # CREATE
                    created_clusters += 1
                    if dry:
                        active_clusters.append({
                            "obj": None,
                            "vector": vec,
                            "id": f"new_{article.id}",
                            "headline": article.title,
                            "entities": a_entities,
                            "topics": a_topics
                        })
                    else:
                        new_cluster_obj = StoryCluster.objects.create(
                            headline=article.title,
                            lead=article.lead or "",
                            cluster_key=f"emb:{article.id}",
                            base_article=article,
                        )
                        self._add_mention(new_cluster_obj, article, score=1.0, is_base=True)
                        touched_clusters.add(new_cluster_obj.id)
                        active_clusters.append({
                            "obj": new_cluster_obj,
                            "vector": vec,
                            "id": new_cluster_obj.id,
                            "headline": new_cluster_obj.headline,
                            "entities": a_entities,
                            "topics": a_topics
                        })

        if not dry and touched_clusters:
            for cluster in StoryCluster.objects.filter(id__in=touched_clusters):
                refresh_cluster_atlas_topics(cluster, save=True)

        if dry:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would create {created_clusters}, join {joined_clusters}."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Created {created_clusters}, Joined {joined_clusters}. Threshold={threshold}"))

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
            if mention.match_score != score:
                mention.match_score = score
                mention.save(update_fields=["match_score"])
