import math
import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import Count

from monitor.models import (
    Article,
    ArticleEntity,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    StoryCluster,
    StoryMention,
)


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
    help = "Cluster articles into story clusters using embeddings."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=400)
        parser.add_argument("--threshold", type=float, default=0.86)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--entity-boost", type=float, default=0.03)
        parser.add_argument("--entity-penalty", type=float, default=0.07)
        parser.add_argument("--skip-entity-guard", action="store_true")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING(f"[DEBUG] cluster_articles_ai file: {__file__}"))
        self.stdout.write(self.style.WARNING(f"[DEBUG] sys.path[0]: {sys.path[0]}"))
        hours = opts["hours"]
        limit = opts["limit"]
        threshold = opts["threshold"]
        dry = opts["dry_run"]
        entity_boost = opts["entity_boost"]
        entity_penalty = opts["entity_penalty"]
        skip_entity_guard = opts["skip_entity_guard"]

        since = timezone.now() - timezone.timedelta(hours=hours)

        articles = list(
            Article.objects.exclude(embedding=[])
            .filter(published_at__gte=since)
            .order_by("-published_at", "-id")[:limit]
        )

        if not articles:
            self.stdout.write(self.style.WARNING("No hay artículos con embedding en la ventana."))
            return

        self.stdout.write(f"Articles in window: {len(articles)} (last {hours}h)")
        self.stdout.write(f"Threshold: {threshold}")

        existing_mentions = set(
            StoryMention.objects.filter(article__in=articles).values_list("article_id", flat=True)
        )

        article_ids = [a.id for a in articles]
        entity_map = self._build_entity_map(article_ids)

        existing_clusters = []
        for cluster in (
            StoryCluster.objects.filter(created_at__gte=since)
            .select_related("base_article")
            .annotate(mention_count=Count("mentions"))
        ):
            base_article = cluster.base_article
            if not base_article or not base_article.embedding:
                continue
            base_entities = entity_map.get(base_article.id, set())
            existing_clusters.append(
                {
                    "cluster": cluster,
                    "centroid": base_article.embedding,
                    "count": max(cluster.mention_count or 0, 1),
                    "entities": base_entities,
                }
            )

        # clusters en memoria
        # cada item: {"cluster": StoryCluster|None, "centroid": list[float], "count": int}
        clusters = list(existing_clusters)
        created_clusters = 0
        created_mentions = 0

        def add_mention(cluster_obj, art):
            nonlocal created_mentions
            _, was_created = StoryMention.objects.get_or_create(
                cluster=cluster_obj,
                article=art,
                defaults={"media_outlet": art.media_outlet},
            )
            if was_created:
                created_mentions += 1

        def update_centroid(centroid, count, vec):
            if not centroid:
                return vec
            total = count + 1
            return [(c * count + v) / total for c, v in zip(centroid, vec)]

        with transaction.atomic():
            for art in articles:
                if art.id in existing_mentions:
                    continue
                vec = art.embedding
                art_entities = entity_map.get(art.id, set())
                best = None
                best_score = -1.0

                for c in clusters:
                    score = cosine(vec, c["centroid"])
                    if not skip_entity_guard:
                        score = self._apply_entity_guard(
                            score,
                            art_entities,
                            c.get("entities", set()),
                            entity_boost,
                            entity_penalty,
                        )
                    if score > best_score:
                        best_score = score
                        best = c

                if best is None or best_score < threshold:
                    # nuevo cluster
                    created_clusters += 1
                    if dry:
                        clusters.append({"cluster": None, "centroid": vec, "count": 1})
                        continue

                    cluster_obj = StoryCluster.objects.create(
                        headline=art.title,
                        lead=getattr(art, "lead", "") or "",
                        cluster_key=f"emb:{art.id}",
                        base_article=art,
                    )
                    clusters.append(
                        {"cluster": cluster_obj, "centroid": vec, "count": 1, "entities": art_entities}
                    )
                    add_mention(cluster_obj, art)
                else:
                    # añadir al mejor cluster
                    best["centroid"] = update_centroid(best["centroid"], best["count"], vec)
                    best["count"] += 1
                    if best.get("entities") is not None:
                        best["entities"] = best["entities"] | art_entities
                    if not dry:
                        add_mention(best["cluster"], art)

        if dry:
            self.stdout.write(self.style.SUCCESS(f"Dry run OK · Candidate clusters: {created_clusters}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Created clusters: {created_clusters} · Created mentions: {created_mentions}"
            ))

    def _build_entity_map(self, article_ids):
        entity_map = {article_id: set() for article_id in article_ids}
        for entry in ArticleEntity.objects.filter(article_id__in=article_ids):
            key = f"{entry.entity_type}:{entry.entity_id}"
            entity_map.setdefault(entry.article_id, set()).add(key)
        for mention in ArticlePersonaMention.objects.filter(article_id__in=article_ids):
            key = f"PERSON:{mention.persona_id}"
            entity_map.setdefault(mention.article_id, set()).add(key)
        for mention in ArticleInstitucionMention.objects.filter(article_id__in=article_ids):
            key = f"INSTITUTION:{mention.institucion_id}"
            entity_map.setdefault(mention.article_id, set()).add(key)
        return entity_map

    def _apply_entity_guard(self, score, article_entities, cluster_entities, boost, penalty):
        if not article_entities or not cluster_entities:
            return score
        if article_entities & cluster_entities:
            return score + boost
        return score - penalty
