from collections import Counter

from django.db.models import Count

from monitor.models import (
    Article,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    ArticleSentiment,
    StoryCluster,
)
from redpolitica.models import Topic


def _sentiment_summary_base():
    return {choice.value: 0 for choice in ArticleSentiment.Sentiment}


def _normalize_topic_label(topic):
    if isinstance(topic, str):
        return topic.strip()
    if isinstance(topic, dict):
        return str(topic.get("label", "")).strip()
    return ""


def build_sentiment_summary(article_ids):
    summary = _sentiment_summary_base()
    if article_ids:
        rows = (
            ArticleSentiment.objects.filter(article_id__in=article_ids)
            .values("sentiment")
            .annotate(total=Count("id"))
        )
        for row in rows:
            sentiment = row["sentiment"]
            if sentiment in summary:
                summary[sentiment] = row["total"]
    summary["total"] = sum(summary.values())
    return summary


def build_topic_summary(article_ids, limit=6):
    counter = Counter()
    if article_ids:
        for topics in Article.objects.filter(id__in=article_ids).values_list("topics", flat=True):
            if not topics:
                continue
            for topic in topics:
                label = _normalize_topic_label(topic)
                if label:
                    counter[label] += 1
    return [
        {"label": label, "total": total}
        for label, total in counter.most_common(limit)
    ]


def build_atlas_topics(article_ids, limit=6):
    if not article_ids:
        return []
    return list(
        Topic.objects.filter(article__id__in=article_ids)
        .annotate(total=Count("article", distinct=True))
        .order_by("-total", "name")[:limit]
    )


def _accumulate_entity_summary(summary_map, entity_type, rows, label_key, id_key):
    for row in rows:
        entity_id = row[id_key]
        label = row[label_key]
        sentiment = row["sentiment"]
        total = row["total"]
        key = (entity_type, entity_id)
        if key not in summary_map:
            summary_map[key] = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "label": label,
                "sentiment_summary": _sentiment_summary_base(),
                "total": 0,
            }
        entry = summary_map[key]
        if sentiment in entry["sentiment_summary"]:
            entry["sentiment_summary"][sentiment] += total


def build_entity_summary(article_ids, limit=6):
    summary_map = {}
    if not article_ids:
        return []

    persona_rows = (
        ArticlePersonaMention.objects.filter(article_id__in=article_ids, sentiment__isnull=False)
        .values("persona_id", "persona__nombre_completo", "sentiment")
        .annotate(total=Count("id"))
    )
    _accumulate_entity_summary(
        summary_map,
        "persona",
        persona_rows,
        "persona__nombre_completo",
        "persona_id",
    )

    institucion_rows = (
        ArticleInstitucionMention.objects.filter(article_id__in=article_ids, sentiment__isnull=False)
        .values("institucion_id", "institucion__nombre", "sentiment")
        .annotate(total=Count("id"))
    )
    _accumulate_entity_summary(
        summary_map,
        "institucion",
        institucion_rows,
        "institucion__nombre",
        "institucion_id",
    )

    for entry in summary_map.values():
        entry["total"] = sum(entry["sentiment_summary"].values())

    summaries = sorted(
        summary_map.values(),
        key=lambda item: (-item["total"], item["label"].lower()),
    )
    return summaries[:limit]


def refresh_cluster_aggregates(cluster: StoryCluster, limit=6, save=True):
    article_ids = list(cluster.mentions.values_list("article_id", flat=True))
    sentiment_summary = build_sentiment_summary(article_ids)
    topic_summary = build_topic_summary(article_ids, limit=limit)
    entity_summary = build_entity_summary(article_ids, limit=limit)
    atlas_topics = build_atlas_topics(article_ids, limit=limit)

    cluster.sentiment_summary = sentiment_summary
    cluster.topic_summary = topic_summary
    cluster.entity_summary = entity_summary

    if save:
        cluster.save(update_fields=["sentiment_summary", "topic_summary", "entity_summary"])
        cluster.atlas_topics.set(atlas_topics)

    return {
        "sentiment_summary": sentiment_summary,
        "topic_summary": topic_summary,
        "entity_summary": entity_summary,
        "atlas_topics": atlas_topics,
    }


def refresh_cluster_atlas_topics(cluster: StoryCluster, limit=6, save=True):
    article_ids = list(cluster.mentions.values_list("article_id", flat=True))
    atlas_topics = build_atlas_topics(article_ids, limit=limit)
    if save:
        cluster.atlas_topics.set(atlas_topics)
    return atlas_topics


def ensure_cluster_aggregates(clusters, limit=6):
    for cluster in clusters:
        if cluster.sentiment_summary and cluster.topic_summary and cluster.entity_summary:
            continue
        refresh_cluster_aggregates(cluster, limit=limit, save=True)
    return clusters
