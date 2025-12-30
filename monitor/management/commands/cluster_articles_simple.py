import re
import hashlib
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from monitor.aggregations import refresh_cluster_atlas_topics
from monitor.models import Article, StoryCluster, StoryMention


STOPWORDS = {
    "el","la","los","las","un","una","unos","unas",
    "de","del","al","y","o","u","en","por","para","con","sin",
    "que","se","a","su","sus","es","son","fue","será","hoy","ayer"
}

def tokenize_title(title: str) -> list[str]:
    t = (title or "").strip().lower()
    # quita urls
    t = re.sub(r"https?://\S+", " ", t)
    # deja letras/números/espacios
    t = re.sub(r"[^\w\sáéíóúñü]", " ", t, flags=re.UNICODE)
    # colapsa espacios
    parts = [p for p in t.split() if p and p not in STOPWORDS]
    # limita para evitar firmas larguísimas
    return parts[:14]

def normalized_text(tokens: list[str]) -> str:
    return " ".join(tokens)


def key_from_norm(norm: str) -> str:
    # key estable corta
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a.intersection(b)
    union = a.union(b)
    return len(inter) / len(union)


class Command(BaseCommand):
    help = "Simple clustering: groups Articles by normalized title into StoryCluster + StoryMention."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
        parser.add_argument("--min-group", type=int, default=2, help="Minimum articles to create a cluster")
        parser.add_argument("--similarity", type=float, default=0.6, help="Jaccard similarity threshold")
        parser.add_argument("--dry-run", action="store_true", help="Do not write, only report")

    def handle(self, *args, **opts):
        hours = opts["hours"]
        min_group = opts["min_group"]
        similarity = opts["similarity"]
        dry = opts["dry_run"]

        since = timezone.now() - timedelta(hours=hours)

        qs = Article.objects.filter(created_at__gte=since).select_related("media_outlet")
        total = qs.count()
        self.stdout.write(self.style.MIGRATE_HEADING(f"Articles in window: {total} (last {hours}h)"))

        groups = []
        for a in qs.iterator():
            tokens = tokenize_title(a.title)
            if not tokens:
                continue
            token_set = set(tokens)
            matched_group = None
            for g in groups:
                score = jaccard(token_set, g["tokens"])
                if score >= similarity:
                    matched_group = g
                    break
            if matched_group:
                matched_group["articles"].append(a)
                matched_group["tokens"] = matched_group["tokens"].union(token_set)
            else:
                groups.append(
                    {
                        "norm": normalized_text(tokens),
                        "tokens": token_set,
                        "articles": [a],
                    }
                )

        # filtra grupos chicos
        clusters = [g for g in groups if len(g["articles"]) >= min_group]
        clusters.sort(key=lambda g: len(g["articles"]), reverse=True)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Candidate clusters (>= {min_group}): {len(clusters)}"))

        if dry:
            for g in clusters[:20]:
                self.stdout.write(f"- {len(g['articles'])} :: {g['articles'][0].title}")
            self.stdout.write(self.style.WARNING("Dry run: no database writes"))
            return

        created_clusters = 0
        created_mentions = 0
        touched_clusters = set()

        with transaction.atomic():
            for g in clusters:
                # si ya existe un cluster con esa key reciente, sáltalo (simple)
                cluster_key = key_from_norm(g["norm"])
                cluster, created = StoryCluster.objects.get_or_create(
                    cluster_key=cluster_key,
                    defaults={
                        "headline": g["articles"][0].title,
                        "lead": (g["articles"][0].lead or "")[:2000],
                        "base_article": g["articles"][0],
                        "confidence": 0.5,
                    },
                )
                if created:
                    created_clusters += 1
                    touched_clusters.add(cluster.id)

                # menciones
                for a in g["articles"]:
                    m, m_created = StoryMention.objects.get_or_create(
                        cluster=cluster,
                        article=a,
                        defaults={
                            "media_outlet": a.media_outlet,
                            "match_score": 0.5,
                            "is_base_candidate": (a.id == cluster.base_article_id),
                        },
                    )
                    if m_created:
                        created_mentions += 1
                        touched_clusters.add(cluster.id)

        if touched_clusters:
            for cluster in StoryCluster.objects.filter(id__in=touched_clusters):
                refresh_cluster_atlas_topics(cluster, save=True)

        self.stdout.write(self.style.SUCCESS(f"Created clusters: {created_clusters}"))
        self.stdout.write(self.style.SUCCESS(f"Created mentions: {created_mentions}"))
