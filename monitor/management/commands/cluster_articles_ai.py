import math
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from monitor.models import Article, StoryCluster, StoryMention


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

    def handle(self, *args, **opts):
        hours = opts["hours"]
        limit = opts["limit"]
        threshold = opts["threshold"]
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

        self.stdout.write(f"Articles in window: {len(articles)} (last {hours}h)")
        self.stdout.write(f"Threshold: {threshold}")

        # clusters en memoria
        # cada item: {"cluster": StoryCluster|None, "centroid": list[float], "count": int}
        clusters = []
        created_clusters = 0
        created_mentions = 0

        def add_mention(cluster_obj, art):
            nonlocal created_mentions
            StoryMention.objects.get_or_create(
                cluster=cluster_obj,
                article=art,
                defaults={"media_outlet": art.media_outlet},
            )
            created_mentions += 1

        with transaction.atomic():
            for art in articles:
                vec = art.embedding
                best = None
                best_score = -1.0

                for c in clusters:
                    score = cosine(vec, c["centroid"])
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
                    )
                    clusters.append({"cluster": cluster_obj, "centroid": vec, "count": 1})
                    add_mention(cluster_obj, art)
                else:
                    # añadir al mejor cluster
                    best["count"] += 1
                    if not dry:
                        add_mention(best["cluster"], art)

        if dry:
            self.stdout.write(self.style.SUCCESS(f"Dry run OK · Candidate clusters: {created_clusters}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Created clusters: {created_clusters} · Created mentions: {created_mentions}"
            ))
