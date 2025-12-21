import hashlib
import json
import math
import os
import random
import importlib
import importlib.util
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from openai import OpenAI

from monitor.models import (
    Article,
    ArticleEntity,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    StoryCluster,
    StoryMention,
)


STOPWORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "y",
    "o",
    "u",
    "en",
    "por",
    "para",
    "con",
    "sin",
    "que",
    "se",
    "a",
    "su",
    "sus",
    "es",
    "son",
    "fue",
    "será",
    "hoy",
    "ayer",
    "este",
    "esta",
    "estos",
    "estas",
    "ante",
    "tras",
    "sobre",
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
        parser.add_argument("--ai-model", type=str, default="gpt-4o-mini")
        parser.add_argument("--skip-ai", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        hours = opts["hours"]
        limit = opts["limit"]
        method = opts["method"]
        min_cluster_size = opts["min_cluster_size"]
        max_clusters = opts["max_clusters"]
        seed = opts["seed"]
        cohesion_threshold = opts["cohesion_threshold"]
        ai_model = opts["ai_model"]
        skip_ai = opts["skip_ai"]
        dry = opts["dry_run"]

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
            self.stdout.write(self.style.WARNING("Todos los artículos ya están clusterizados."))
            return

        article_ids = [article.id for article in unclustered]
        entity_map = self._build_entity_map(article_ids)
        keyword_map = {
            article.id: build_keywords(article.title, article.lead, article.body_text)
            for article in unclustered
        }

        embeddings = [article.embedding for article in unclustered]
        initial_clusters = self._initial_stage(embeddings, method, min_cluster_size, max_clusters, seed)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Stage A · {len(initial_clusters)} clusters iniciales ({len(unclustered)} artículos)"
            )
        )

        ai_client = None
        if not skip_ai and os.environ.get("OPENAI_API_KEY"):
            ai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=20)
        elif not skip_ai:
            self.stdout.write(self.style.WARNING("OPENAI_API_KEY no configurada: se omite validación IA."))

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

        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(final_clusters)} clusters finales · IA splits={ai_splits} · heuristic splits={heuristic_splits}"
                )
            )
            return

        with transaction.atomic():
            for entry in final_clusters:
                cluster_articles = entry["articles"]
                ai_meta = entry["ai"]
                metrics = self._compute_cluster_metrics(cluster_articles, entity_map, keyword_map)

                base_article, centroid = self._select_base_article(cluster_articles)
                article_ids = sorted([article.id for article in cluster_articles])
                cluster_key = self._cluster_key(article_ids)

                topic_label = metrics["topic_label"]
                cluster_summary = metrics["cluster_summary"]

                if ai_meta:
                    topic_label = ai_meta.get("topic_label") or topic_label
                    cluster_summary = ai_meta.get("cluster_summary") or cluster_summary

                cluster, created = StoryCluster.objects.get_or_create(
                    cluster_key=cluster_key,
                    defaults={
                        "headline": base_article.title,
                        "lead": base_article.lead or "",
                        "base_article": base_article,
                        "confidence": metrics["cohesion_score"],
                        "topic_label": topic_label,
                        "cohesion_score": metrics["cohesion_score"],
                        "cluster_summary": cluster_summary,
                    },
                )
                if created:
                    created_clusters += 1
                else:
                    StoryCluster.objects.filter(id=cluster.id).update(
                        headline=base_article.title,
                        lead=base_article.lead or "",
                        base_article=base_article,
                        confidence=metrics["cohesion_score"],
                        topic_label=topic_label,
                        cohesion_score=metrics["cohesion_score"],
                        cluster_summary=cluster_summary,
                    )

                for article in cluster_articles:
                    match_score = cosine(article.embedding, centroid) if centroid else 0.0
                    _, was_created = StoryMention.objects.get_or_create(
                        cluster=cluster,
                        article=article,
                        defaults={
                            "media_outlet": article.media_outlet,
                            "match_score": match_score,
                            "is_base_candidate": article.id == base_article.id,
                        },
                    )
                    if was_created:
                        created_mentions += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Created clusters: {} · Created mentions: {} · IA splits: {} · heuristic splits: {}".format(
                    created_clusters,
                    created_mentions,
                    ai_splits,
                    heuristic_splits,
                )
            )
        )

    def _cluster_key(self, article_ids):
        digest = hashlib.sha1("-".join(map(str, article_ids)).encode("utf-8")).hexdigest()
        return f"ai2:{digest[:16]}"

    def _select_base_article(self, articles):
        embeddings = [article.embedding for article in articles]
        centroid = average_vectors(embeddings)
        best_article = articles[0]
        best_score = -1.0
        for article in articles:
            score = cosine(article.embedding, centroid)
            if score > best_score:
                best_score = score
                best_article = article
        return best_article, centroid

    def _initial_stage(self, embeddings, method, min_cluster_size, max_clusters, seed):
        total = len(embeddings)
        if total == 0:
            return []
        if total <= min_cluster_size:
            return [[idx] for idx in range(total)]

        hdbscan_module = load_optional_module("hdbscan")

        if method == "auto" and hdbscan_module:
            method = "hdbscan"
        if method == "hdbscan" and not hdbscan_module:
            self.stdout.write(self.style.WARNING("HDBSCAN no disponible, usando KMeans."))
            method = "kmeans"

        if method == "hdbscan" and hdbscan_module:
            clusterer = hdbscan_module.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
            labels = clusterer.fit_predict(embeddings)
            clusters = {}
            for idx, label in enumerate(labels):
                clusters.setdefault(label, []).append(idx)
            results = [group for label, group in clusters.items() if label != -1]
            noise = clusters.get(-1, [])
            results.extend([[idx] for idx in noise])
            return results

        cluster_count = min(max_clusters, max(1, int(math.sqrt(total))))
        return kmeans_clusters(embeddings, cluster_count, seed=seed)

    def _compute_cluster_metrics(self, articles, entity_map, keyword_map):
        embeddings = [article.embedding for article in articles]
        centroid = average_vectors(embeddings)
        thematic_scores = [cosine(article.embedding, centroid) for article in articles]
        thematic_similarity = sum(thematic_scores) / len(thematic_scores) if thematic_scores else 0.0

        entity_sets = [entity_map.get(article.id, set()) for article in articles]
        keyword_sets = [keyword_map.get(article.id, set()) for article in articles]

        entity_overlap = compute_overlap_score(entity_sets)
        keyword_overlap = compute_overlap_score(keyword_sets)

        cohesion_score = 0.5 * thematic_similarity + 0.25 * entity_overlap + 0.25 * keyword_overlap

        keywords_counter = Counter()
        for keywords in keyword_sets:
            keywords_counter.update(keywords)
        topic_label = build_topic_label([word for word, _ in keywords_counter.most_common(5)])
        example_title = articles[0].title if articles else ""
        cluster_summary = build_cluster_summary(topic_label, len(articles), example_title)

        return {
            "cohesion_score": cohesion_score,
            "topic_label": topic_label,
            "cluster_summary": cluster_summary,
        }

    def _ai_split_cluster(self, client, model, articles, entity_map, keyword_map):
        payload = []
        for idx, article in enumerate(articles):
            payload.append(
                {
                    "index": idx,
                    "title": (article.title or "")[:180],
                    "lead": (article.lead or "")[:240],
                    "keywords": sorted(keyword_map.get(article.id, []))[:10],
                    "entities": sorted(entity_map.get(article.id, []))[:10],
                }
            )

        prompt = (
            "Revisa si el cluster de noticias es coherente. "
            "Si es coherente, responde con is_coherent=true y un topic_label y cluster_summary. "
            "Si no es coherente, divide en grupos coherentes y entrega los índices por grupo. "
            "Responde SOLO JSON con llaves: is_coherent (true/false), topic_label, cluster_summary, "
            "groups (lista de objetos con indices, topic_label, cluster_summary). "
            "Usa los índices tal como se entregan."
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Eres un analista editorial. Responde SOLO JSON."},
                    {"role": "user", "content": f"{prompt}\n\nArtículos: {json.dumps(payload, ensure_ascii=False)}"},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Error OpenAI (cluster validation): {exc}"))
            return None

        content = response.choices[0].message.content
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            self.stdout.write(self.style.WARNING("JSON inválido en validación IA."))
            return None

        if not isinstance(result, dict):
            return None

        if result.get("is_coherent") is True:
            return None

        raw_groups = result.get("groups") or []
        groups = []
        for group in raw_groups:
            indices = group.get("indices") or []
            indices = [idx for idx in indices if isinstance(idx, int) and 0 <= idx < len(articles)]
            if not indices:
                continue
            group_articles = [articles[idx] for idx in indices]
            groups.append(
                {
                    "articles": group_articles,
                    "topic_label": group.get("topic_label") or "",
                    "cluster_summary": group.get("cluster_summary") or "",
                }
            )

        if not groups:
            return None

        return {"groups": groups}

    def _heuristic_split(self, articles, seed):
        if len(articles) < 4:
            return None
        embeddings = [article.embedding for article in articles]
        clusters = kmeans_clusters(embeddings, 2, seed=seed)
        if len(clusters) < 2:
            return None
        return [[articles[idx] for idx in cluster] for cluster in clusters]

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
