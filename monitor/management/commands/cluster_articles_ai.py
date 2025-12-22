import hashlib
import importlib
import json
import math
import os
import random
import sys
from collections import Counter
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from monitor.models import (
    Article,
    ArticleEntity,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    StoryCluster,
    StoryMention,
)

STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "y", "o", "u", "en", "por", "para", "con", "sin",
    "que", "se", "a", "su", "sus", "es", "son", "fue", "será", "hoy", "ayer",
}


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


def tokenize_text(text):
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in (text or ""))
    tokens = [token for token in cleaned.split() if token and token not in STOPWORDS]
    return tokens


def build_keywords(title, lead, body_text, limit=12):
    tokens = tokenize_text(f"{title} {lead} {body_text}")
    counts = Counter(tokens)
    return {word for word, _ in counts.most_common(limit)}


def average_vectors(vectors):
    if not vectors:
        return []
    dim = len(vectors[0])
    totals = [0.0] * dim
    for vec in vectors:
        for idx, val in enumerate(vec):
            totals[idx] += val
    return [val / len(vectors) for val in totals]


def load_optional_module(name):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    return importlib.import_module(name)


def kmeans_clusters(embeddings, cluster_count, seed=42, max_iters=15):
    total = len(embeddings)
    if total == 0:
        return []
    if cluster_count >= total:
        return [[idx] for idx in range(total)]

    rng = random.Random(seed)
    centroid_indices = rng.sample(range(total), cluster_count)
    centroids = [embeddings[idx][:] for idx in centroid_indices]

    assignments = [0] * total
    for _ in range(max_iters):
        changed = False
        for idx, vec in enumerate(embeddings):
            best_cluster = 0
            best_score = -1.0
            for c_idx, centroid in enumerate(centroids):
                score = cosine(vec, centroid)
                if score > best_score:
                    best_score = score
                    best_cluster = c_idx
            if assignments[idx] != best_cluster:
                assignments[idx] = best_cluster
                changed = True

        new_centroids = [[] for _ in range(cluster_count)]
        for idx, cluster_id in enumerate(assignments):
            new_centroids[cluster_id].append(embeddings[idx])

        for cluster_id, vectors in enumerate(new_centroids):
            if not vectors:
                centroids[cluster_id] = embeddings[rng.randrange(total)][:]
            else:
                centroids[cluster_id] = average_vectors(vectors)

        if not changed:
            break

    clusters = [[] for _ in range(cluster_count)]
    for idx, cluster_id in enumerate(assignments):
        clusters[cluster_id].append(idx)

    return [cluster for cluster in clusters if cluster]


def compute_overlap_score(sets):
    if not sets:
        return 0.0
    union = set().union(*sets)
    if not union:
        return 0.0
    scores = []
    for item in sets:
        if not item:
            scores.append(0.0)
            continue
        scores.append(len(item & union) / len(union))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def build_topic_label(keywords):
    if not keywords:
        return ""
    return ", ".join(keywords[:3])


def build_cluster_summary(topic_label, article_count, example_title):
    if not topic_label:
        topic_label = example_title[:120]
    if article_count == 1:
        return f"Cobertura única sobre {topic_label}."
    return f"Cobertura con {article_count} artículos sobre {topic_label}."


class Command(BaseCommand):
    help = "Cluster articles into story clusters using a 2-stage pipeline (embeddings + semantic validation)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=400)
        parser.add_argument("--method", type=str, default="auto", choices=["auto", "hdbscan", "kmeans"])
        parser.add_argument("--min-cluster-size", type=int, default=3)
        parser.add_argument("--max-clusters", type=int, default=12)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--cohesion-threshold", type=float, default=0.55)
        parser.add_argument("--threshold", type=float, default=None, help="Alias de --cohesion-threshold")
        parser.add_argument("--ai-model", type=str, default="gpt-4o-mini")
        parser.add_argument("--skip-ai", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--entity-boost", type=float, default=0.03)
        parser.add_argument("--entity-penalty", type=float, default=0.07)
        parser.add_argument("--skip-entity-guard", action="store_true")

    def handle(self, *args, **opts):
        from django.db.models import Count as Count  # noqa: PLC0415

        self.stdout.write(self.style.WARNING(f"[DEBUG] cluster_articles_ai file: {__file__}"))
        self.stdout.write(self.style.WARNING(f"[DEBUG] sys.path[0]: {sys.path[0]}"))
        hours = opts["hours"]
        limit = opts["limit"]
        method = opts["method"]
        min_cluster_size = opts["min_cluster_size"]
        max_clusters = opts["max_clusters"]
        seed = opts["seed"]
        cohesion_threshold = opts["cohesion_threshold"]
        if opts.get("threshold") is not None:
            cohesion_threshold = opts["threshold"]
        ai_model = opts["ai_model"]
        skip_ai = opts["skip_ai"]
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

        existing_mentions = set(
            StoryMention.objects.filter(article__in=articles).values_list("article_id", flat=True)
        )
        unclustered = [article for article in articles if article.id not in existing_mentions]

        if not unclustered:
            self.stdout.write(self.style.WARNING("No hay artículos nuevos sin cluster en la ventana."))
            return

        article_ids = [a.id for a in articles]
        entity_map = self._build_entity_map(article_ids)

        keyword_map = {
            article.id: build_keywords(
                article.title or "",
                getattr(article, "lead", "") or "",
                getattr(article, "body_text", "") or "",
            )
            for article in unclustered
        }

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

        ai_client = None
        if not skip_ai and os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
            except ImportError:
                self.stdout.write(self.style.WARNING("Paquete openai no disponible. Se omite validación IA."))
            else:
                ai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=20)
        elif not skip_ai:
            self.stdout.write(self.style.WARNING("OPENAI_API_KEY no configurada: se omite validación IA."))

        embeddings = [article.embedding for article in unclustered]
        initial_clusters = self._build_initial_clusters(
            embeddings,
            method=method,
            min_cluster_size=min_cluster_size,
            max_clusters=max_clusters,
            seed=seed,
        )

        final_clusters = []
        ai_splits = 0
        heuristic_splits = 0

        for cluster_indices in initial_clusters:
            cluster_articles = [unclustered[idx] for idx in cluster_indices]
            metrics = self._compute_cluster_metrics(cluster_articles, entity_map, keyword_map)

            if metrics["cohesion_score"] < cohesion_threshold and len(cluster_articles) >= 4:
                split_result = None
                if ai_client:
                    split_result = self._ai_split_cluster(
                        ai_client,
                        ai_model,
                        cluster_articles,
                        entity_map,
                        keyword_map,
                    )
                if split_result:
                    ai_splits += 1
                    for group in split_result["groups"]:
                        final_clusters.append({"articles": group["articles"], "ai": group})
                    continue
                heuristic_groups = self._heuristic_split(cluster_articles, seed)
                if heuristic_groups:
                    heuristic_splits += 1
                    for group in heuristic_groups:
                        final_clusters.append({"articles": group, "ai": None})
                    continue

            final_clusters.append({"articles": cluster_articles, "ai": None})

        created_clusters = 0
        created_mentions = 0
        clusters = list(existing_clusters)
        threshold = cohesion_threshold

        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(final_clusters)} clusters finales · IA splits={ai_splits} · heuristic splits={heuristic_splits}"
                )
            )
            return

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
                    if self._add_mention(cluster_obj, art, score=best_score, is_base=True):
                        created_mentions += 1
                else:
                    # añadir al mejor cluster
                    best["centroid"] = update_centroid(best["centroid"], best["count"], vec)
                    best["count"] += 1
                    if best.get("entities") is not None:
                        best["entities"] = best["entities"] | art_entities
                    if not dry:
                        if self._add_mention(best["cluster"], art, score=best_score):
                            created_mentions += 1

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

    def _build_initial_clusters(self, embeddings, method, min_cluster_size, max_clusters, seed):
        if not embeddings:
            return []
        cluster_count = max(1, len(embeddings) // max(min_cluster_size, 1))
        cluster_count = min(max_clusters, cluster_count)
        if method == "hdbscan":
            self.stdout.write(self.style.WARNING("hdbscan no disponible; usando kmeans como fallback."))
        return kmeans_clusters(embeddings, cluster_count, seed=seed)

    def _compute_cluster_metrics(self, cluster_articles, entity_map, keyword_map):
        embeddings = [article.embedding for article in cluster_articles if article.embedding]
        centroid = average_vectors(embeddings)
        if centroid:
            cohesion_score = sum(cosine(vec, centroid) for vec in embeddings) / len(embeddings)
        else:
            cohesion_score = 0.0
        entity_overlap = compute_overlap_score([entity_map.get(article.id, set()) for article in cluster_articles])
        keyword_overlap = compute_overlap_score([keyword_map.get(article.id, set()) for article in cluster_articles])
        return {
            "cohesion_score": (cohesion_score + entity_overlap + keyword_overlap) / 3.0,
            "entity_overlap": entity_overlap,
            "keyword_overlap": keyword_overlap,
            "size": len(cluster_articles),
        }

    def _heuristic_split(self, cluster_articles, seed):
        if len(cluster_articles) < 4:
            return None
        embeddings = [article.embedding for article in cluster_articles if article.embedding]
        if len(embeddings) < 4:
            return None
        clusters = kmeans_clusters(embeddings, 2, seed=seed)
        if len(clusters) < 2:
            return None
        return [[cluster_articles[idx] for idx in group] for group in clusters if len(group) >= 2]

    def _ai_split_cluster(self, client, model, cluster_articles, entity_map, keyword_map):
        return None

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
        if not created and (mention.match_score != score or mention.is_base_candidate != is_base):
            mention.match_score = score
            mention.is_base_candidate = is_base
            mention.save(update_fields=["match_score", "is_base_candidate"])
        return created


def update_centroid(centroid, count, vector):
    if not centroid:
        return vector[:]
    total = []
    for idx, val in enumerate(vector):
        prev = centroid[idx] if idx < len(centroid) else 0.0
        total.append((prev * count + val) / (count + 1))
    return total
