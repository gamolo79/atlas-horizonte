from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, List, Tuple

from django.conf import settings
from django.db import transaction

from monitor.models import Article
from sintesis.models import (
    SynthesisArticleMentionStrength,
    SynthesisCluster,
    SynthesisClusterMember,
    SynthesisRun,
    SynthesisSectionTemplate,
)
from sintesis.services.embeddings import cosine_similarity, nearest_embeddings


def _article_vector(article: Article) -> List[float]:
    cache = getattr(article, "embedding_cache", None)
    if not cache:
        return []
    return list(cache.embedding_json or [])


def _article_tags(article: Article) -> set[str]:
    classification = getattr(article, "classification", None)
    return set(getattr(classification, "labels_json", []) or [])


def _article_entities(article: Article) -> dict[str, str]:
    classification = getattr(article, "classification", None)
    entities = {}
    if not classification:
        return entities
    for mention in classification.mentions.all():
        key = f"{mention.target_type}:{mention.target_id}"
        entities[key] = mention.target_name
    return entities


def _strong_entity_keys(article: Article) -> set[str]:
    strengths = SynthesisArticleMentionStrength.objects.filter(
        article=article,
        strength="strong",
    )
    return {f"{item.target_type}:{item.target_id}" for item in strengths}


def _cluster_vector(members: Iterable[SynthesisClusterMember]) -> List[float]:
    vectors = []
    for member in members:
        vector = _article_vector(member.article)
        if vector:
            vectors.append(vector)
    if not vectors:
        return []
    dims = len(vectors[0])
    sums = [0.0] * dims
    for vector in vectors:
        for idx, value in enumerate(vector):
            sums[idx] += value
    return [value / len(vectors) for value in sums]


def _gating_passes(article: Article, cluster: SynthesisCluster) -> Tuple[bool, dict]:
    strong_keys = _strong_entity_keys(article)
    cluster_entities = set(cluster.top_entities_json or [])
    tag_overlap = _article_tags(article) & set(cluster.top_tags_json or [])
    strong_overlap = strong_keys & cluster_entities
    reasons = {
        "strong_overlap": sorted(strong_overlap),
        "tag_overlap": sorted(tag_overlap),
    }
    if strong_overlap:
        return True, reasons
    if len(tag_overlap) >= 2:
        return True, reasons
    return False, reasons


def _collect_cluster_metadata(articles: List[Article]) -> Tuple[list[str], list[str]]:
    entity_counts = Counter()
    tag_counts = Counter()
    for article in articles:
        for key, name in _article_entities(article).items():
            entity_counts[key] += 1
        for tag in _article_tags(article):
            tag_counts[tag] += 1
    top_entities = [key for key, _count in entity_counts.most_common(6)]
    top_tags = [tag for tag, _count in tag_counts.most_common(6)]
    return top_entities, top_tags


def _candidate_clusters(run: SynthesisRun, template: SynthesisSectionTemplate) -> List[SynthesisCluster]:
    return list(
        SynthesisCluster.objects.filter(run=run, template=template).order_by("-created_at")
    )


def assign_articles_to_clusters(
    run: SynthesisRun,
    template: SynthesisSectionTemplate,
    articles: List[Article],
) -> List[SynthesisCluster]:
    clusters = _candidate_clusters(run, template)
    created_clusters = []

    for article in articles:
        vector = _article_vector(article)
        best_cluster = None
        best_score = 0.0
        best_reasons = {}

        if clusters and vector:
            cluster_vectors = [cluster.centroid_json for cluster in clusters]
            candidates = nearest_embeddings(vector, cluster_vectors, top_k=5)
        else:
            candidates = [(idx, 0.0) for idx in range(len(clusters))]

        for idx, score in candidates:
            cluster = clusters[idx]
            if vector and cluster.centroid_json:
                score = cosine_similarity(vector, cluster.centroid_json)
            passes_gate, reasons = _gating_passes(article, cluster)
            if not passes_gate:
                continue
            threshold = 0.86 if reasons.get("strong_overlap") else 0.90
            if score >= threshold and score > best_score:
                best_score = score
                best_cluster = cluster
                best_reasons = reasons

        if best_cluster:
            with transaction.atomic():
                SynthesisClusterMember.objects.create(
                    cluster=best_cluster,
                    article=article,
                    similarity=best_score,
                    matched_signals_json=best_reasons,
                    is_strong_match=bool(best_reasons.get("strong_overlap")),
                )
                members = best_cluster.members.select_related("article")
                best_cluster.centroid_json = _cluster_vector(members)
                articles_in_cluster = [member.article for member in members]
                top_entities, top_tags = _collect_cluster_metadata(articles_in_cluster)
                best_cluster.top_entities_json = top_entities
                best_cluster.top_tags_json = top_tags
                best_cluster.time_start = min(
                    [member.article.published_at or member.article.fetched_at for member in members]
                )
                best_cluster.time_end = max(
                    [member.article.published_at or member.article.fetched_at for member in members]
                )
                best_cluster.save(
                    update_fields=[
                        "centroid_json",
                        "top_entities_json",
                        "top_tags_json",
                        "time_start",
                        "time_end",
                    ]
                )
        else:
            now = datetime.now()
            with transaction.atomic():
                cluster = SynthesisCluster.objects.create(
                    run=run,
                    template=template,
                    centroid_json=vector or [],
                    top_entities_json=list(_strong_entity_keys(article)),
                    top_tags_json=list(_article_tags(article))[:6],
                    time_start=article.published_at or article.fetched_at or now,
                    time_end=article.published_at or article.fetched_at or now,
                )
                SynthesisClusterMember.objects.create(
                    cluster=cluster,
                    article=article,
                    similarity=1.0,
                    matched_signals_json={"seed": True},
                    is_strong_match=True,
                )
            clusters.append(cluster)
            created_clusters.append(cluster)

    if settings.SINTESIS_ENABLE_CLUSTER_MERGE:
        merge_clusters(run, template)
    return created_clusters


def merge_clusters(run: SynthesisRun, template: SynthesisSectionTemplate) -> None:
    clusters = list(
        SynthesisCluster.objects.filter(run=run, template=template).order_by("-created_at")
    )
    for idx, cluster in enumerate(clusters):
        for other in clusters[idx + 1 :]:
            if not cluster.centroid_json or not other.centroid_json:
                continue
            score = cosine_similarity(cluster.centroid_json, other.centroid_json)
            shared_entities = set(cluster.top_entities_json or []) & set(other.top_entities_json or [])
            shared_tags = set(cluster.top_tags_json or []) & set(other.top_tags_json or [])
            if score <= 0.90 or (not shared_entities and len(shared_tags) < 3):
                continue
            _merge_pair(cluster, other)


def _merge_pair(primary: SynthesisCluster, secondary: SynthesisCluster) -> None:
    with transaction.atomic():
        secondary.members.update(cluster=primary)
        members = primary.members.select_related("article")
        primary.centroid_json = _cluster_vector(members)
        articles = [member.article for member in members]
        top_entities, top_tags = _collect_cluster_metadata(articles)
        primary.top_entities_json = top_entities
        primary.top_tags_json = top_tags
        primary.time_start = min(
            [member.article.published_at or member.article.fetched_at for member in members]
        )
        primary.time_end = max(
            [member.article.published_at or member.article.fetched_at for member in members]
        )
        primary.save(
            update_fields=[
                "centroid_json",
                "top_entities_json",
                "top_tags_json",
                "time_start",
                "time_end",
            ]
        )
        secondary.delete()
