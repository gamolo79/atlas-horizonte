from __future__ import annotations

import hashlib

from django.db import models


class IngestRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    action = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    time_window_start = models.DateTimeField(null=True, blank=True)
    time_window_end = models.DateTimeField(null=True, blank=True)
    stats_seen = models.IntegerField(default=0)
    stats_new = models.IntegerField(default=0)
    stats_errors = models.IntegerField(default=0)
    log_text = models.TextField(blank=True)
    error_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self) -> str:
        return f"{self.action} ({self.status})"


class MediaOutlet(models.Model):
    name = models.CharField(max_length=200, unique=True)
    site_url = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class MediaSource(models.Model):
    media_outlet = models.ForeignKey(MediaOutlet, on_delete=models.CASCADE)
    url = models.URLField()
    source_type = models.CharField(max_length=20, default="rss")
    is_active = models.BooleanField(default=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["media_outlet", "is_active"]),
            models.Index(fields=["last_fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.media_outlet.name} · {self.source_type}"


class Article(models.Model):
    outlet = models.ForeignKey(MediaOutlet, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.ForeignKey(MediaSource, null=True, blank=True, on_delete=models.SET_NULL)
    url = models.URLField(unique=True)
    title = models.TextField()
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    lead = models.TextField(blank=True)
    body = models.TextField(blank=True)
    language = models.CharField(max_length=20, blank=True)
    hash_dedupe = models.CharField(max_length=64, blank=True, db_index=True)
    pipeline_status = models.CharField(max_length=20, default="new")

    class Meta:
        indexes = [
            models.Index(fields=["pipeline_status", "published_at"]),
            models.Index(fields=["outlet", "published_at"]),
        ]
        ordering = ["-published_at", "-id"]

    def __str__(self) -> str:
        return self.title[:120]

    @staticmethod
    def compute_hash(url: str) -> str:
        return hashlib.sha256((url or "").encode("utf-8")).hexdigest()


class StoryCluster(models.Model):
    run = models.ForeignKey(IngestRun, null=True, blank=True, on_delete=models.SET_NULL)
    cluster_key = models.CharField(max_length=200, blank=True)
    headline = models.TextField()
    lead = models.TextField(blank=True)
    base_article = models.ForeignKey(Article, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    confidence = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["run", "confidence"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.headline[:120]


class StoryMention(models.Model):
    cluster = models.ForeignKey(StoryCluster, on_delete=models.CASCADE, related_name="mentions")
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    media_outlet = models.ForeignKey(MediaOutlet, on_delete=models.CASCADE)
    match_score = models.FloatField(default=0.0)
    is_base_candidate = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cluster", "article"], name="uniq_cluster_article"),
        ]
        indexes = [
            models.Index(fields=["cluster", "media_outlet"]),
        ]

    def __str__(self) -> str:
        return f"{self.cluster_id} · {self.article_id}"
