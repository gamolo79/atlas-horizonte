from __future__ import annotations

import hashlib
from typing import Optional

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class MediaOutlet(models.Model):
    class MediaType(models.TextChoices):
        DIGITAL_NATIVE = "digital_native", "Digital nativo"
        BROADCAST_WITH_WEB = "broadcast_with_web", "Radio/TV con web"
        PRINT_WITH_WEB = "print_with_web", "Impreso con web"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    type = models.CharField(max_length=30, choices=MediaType.choices)
    home_url = models.URLField(blank=True)
    weight = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["type", "is_active"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class MediaSource(models.Model):
    class SourceType(models.TextChoices):
        RSS = "rss", "RSS"
        SITEMAP = "sitemap", "Sitemap"
        SECTION_URL = "section_url", "Sección/URL"
        API = "api", "API"
        MANUAL_URL = "manual_url", "Manual"

    media_outlet = models.ForeignKey(MediaOutlet, on_delete=models.CASCADE, related_name="sources")
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    url = models.URLField()
    scan_interval_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)

    last_fetched_at = models.DateTimeField(null=True, blank=True)
    fail_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["media_outlet", "is_active"]),
            models.Index(fields=["last_fetched_at"]),
        ]

    def __str__(self):
        return f"{self.media_outlet.name} · {self.source_type}"


class IngestRun(models.Model):
    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Programada"
        MANUAL = "manual", "Manual"
        RETRY = "retry", "Reintento"

    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        RUNNING = "running", "Corriendo"
        SUCCESS = "success", "Exitosa"
        FAILED = "failed", "Fallida"
        PARTIAL = "partial", "Parcial"

    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    time_window_start = models.DateTimeField()
    time_window_end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)

    stats_total_fetched = models.PositiveIntegerField(default=0)
    stats_total_parsed = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    log = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        indexes = [
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["time_window_start", "time_window_end"]),
        ]


class Source(models.Model):
    class SourceType(models.TextChoices):
        RSS = "rss", "RSS"
        SITEMAP = "sitemap", "Sitemap"
        HTML = "html", "HTML"
        API = "api", "API"

    name = models.CharField(max_length=200)
    outlet = models.CharField(max_length=200)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    url = models.URLField(max_length=1000)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "is_active"]),
            models.Index(fields=["outlet"]),
        ]
        ordering = ["outlet", "name"]

    def __str__(self) -> str:
        return f"{self.outlet} · {self.name}"


class Article(models.Model):
    class PipelineStatus(models.TextChoices):
        INGESTED = "ingested", "Ingestada"
        NORMALIZED = "normalized", "Normalizada"
        CLASSIFIED = "classified", "Clasificada"
        CLUSTERED = "clustered", "Clusterizada"
        AGGREGATED = "aggregated", "Agregada"
        DIGESTED = "digested", "En síntesis"
        ERROR = "error", "Error"

    source = models.ForeignKey(Source, null=True, blank=True, on_delete=models.SET_NULL)
    url = models.URLField(max_length=1000, unique=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    title = models.TextField()
    lead = models.TextField(blank=True)
    body = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    outlet = models.CharField(max_length=200, blank=True)
    language = models.CharField(max_length=10, default="es")
    hash_dedupe = models.CharField(max_length=64, db_index=True)
    raw_html = models.TextField(blank=True)
    pipeline_status = models.CharField(
        max_length=20,
        choices=PipelineStatus.choices,
        default=PipelineStatus.INGESTED,
    )
    pipeline_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["pipeline_status", "published_at"]),
            models.Index(fields=["hash_dedupe"]),
            models.Index(fields=["outlet", "published_at"]),
        ]
        ordering = ["-published_at", "-id"]

    def __str__(self) -> str:
        return self.title[:80]

    @staticmethod
    def compute_hash(url: str, canonical_url: Optional[str], body: str) -> str:
        seed = (canonical_url or url or "").strip().lower() + "|" + (body or "").strip()
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class StoryCluster(models.Model):
    run = models.ForeignKey(IngestRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="clusters")
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

    def __str__(self):
        return self.headline[:80]


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
        ordering = ["cluster_id", "media_outlet_id", "id"]


class ArticleVersion(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField(default=1)
    title = models.TextField()
    lead = models.TextField(blank=True)
    body = models.TextField(blank=True)
    cleaned_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["article", "version"]),
        ]
        ordering = ["-version", "-id"]


class ClassificationRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        RUNNING = "running", "Corriendo"
        SUCCESS = "success", "Exitosa"
        FAILED = "failed", "Fallida"

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="classification_runs")
    model_name = models.CharField(max_length=120)
    model_version = models.CharField(max_length=80, blank=True)
    prompt_version = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    tokens = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "started_at"]),
        ]


class Extraction(models.Model):
    class ContentType(models.TextChoices):
        INFORMATIVO = "informativo", "Informativo"
        OPINION = "opinion", "Opinión"
        BOLETIN = "boletin", "Boletín"
        ANALISIS = "analisis", "Análisis"

    class Scope(models.TextChoices):
        FEDERAL = "federal", "Federal"
        ESTATAL = "estatal", "Estatal"
        MUNICIPAL = "municipal", "Municipal"

    classification_run = models.OneToOneField(
        ClassificationRun,
        on_delete=models.CASCADE,
        related_name="extraction",
    )
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    institutional_type = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "scope"]),
        ]


class DecisionTrace(models.Model):
    classification_run = models.ForeignKey(
        ClassificationRun,
        on_delete=models.CASCADE,
        related_name="decision_traces",
    )
    field_name = models.CharField(max_length=120)
    value = models.CharField(max_length=250)
    confidence = models.FloatField(default=0.0)
    rationale = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["field_name"]),
        ]


class ActorLink(models.Model):
    class AtlasEntityType(models.TextChoices):
        PERSONA = "persona", "Persona"
        INSTITUCION = "institucion", "Institución"

    class Sentiment(models.TextChoices):
        POSITIVO = "positivo", "Positivo"
        NEUTRO = "neutro", "Neutro"
        NEGATIVO = "negativo", "Negativo"

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="actor_links")
    atlas_entity_id = models.CharField(max_length=120)
    atlas_entity_type = models.CharField(max_length=20, choices=AtlasEntityType.choices)
    role_in_article = models.CharField(max_length=120, blank=True)
    sentiment = models.CharField(max_length=20, choices=Sentiment.choices)
    sentiment_confidence = models.FloatField(default=0.0)
    rationale = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["atlas_entity_type", "atlas_entity_id"]),
            models.Index(fields=["sentiment"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "atlas_entity_id", "atlas_entity_type"],
                name="unique_actor_per_article",
            ),
        ]


class TopicLink(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="topic_links")
    atlas_topic_id = models.CharField(max_length=120)
    confidence = models.FloatField(default=0.0)
    rationale = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["atlas_topic_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["article", "atlas_topic_id"], name="unique_topic_per_article"),
        ]


class EditorialTag(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    is_global = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TagLink(models.Model):
    tag = models.ForeignKey(EditorialTag, on_delete=models.CASCADE, related_name="links")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tag", "content_type", "object_id"],
                name="unique_tag_link",
            )
        ]


class Story(models.Model):
    class Status(models.TextChoices):
        PROPUESTA = "propuesta", "Propuesta"
        CONFIRMADA = "confirmada", "Confirmada"
        CORREGIDA = "corregida", "Corregida"

    title_base = models.TextField()
    lead_base = models.TextField(blank=True)
    main_topic_id = models.CharField(max_length=120, blank=True)
    time_window_start = models.DateTimeField()
    time_window_end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPUESTA)

    class Meta:
        indexes = [
            models.Index(fields=["time_window_start", "time_window_end"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-time_window_start", "-id"]

    def __str__(self) -> str:
        return self.title_base[:80]


class StoryActor(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="main_actors")
    atlas_entity_id = models.CharField(max_length=120)
    atlas_entity_type = models.CharField(max_length=20, choices=ActorLink.AtlasEntityType.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["story", "atlas_entity_id", "atlas_entity_type"],
                name="unique_story_actor",
            )
        ]


class StoryArticle(models.Model):
    class AddedBy(models.TextChoices):
        AI = "ai", "IA"
        HUMAN = "human", "Humano"

    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="story_articles")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="story_articles")
    is_representative = models.BooleanField(default=False)
    added_by = models.CharField(max_length=10, choices=AddedBy.choices, default=AddedBy.AI)
    confidence = models.FloatField(default=0.0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["story", "article"], name="unique_story_article"),
        ]
        indexes = [
            models.Index(fields=["story", "is_representative"]),
        ]


class Client(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ClientFocus(models.Model):
    class EntityType(models.TextChoices):
        PERSONA = "persona", "Persona"
        INSTITUCION = "institucion", "Institución"
        TEMA = "tema", "Tema"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="focus_items")
    entity_type = models.CharField(max_length=20, choices=EntityType.choices)
    atlas_id = models.CharField(max_length=120)
    priority = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=["client", "entity_type"]),
            models.Index(fields=["atlas_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "entity_type", "atlas_id"],
                name="unique_client_focus",
            )
        ]


class DailyExecution(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        RUNNING = "running", "Corriendo"
        SUCCESS = "success", "Exitosa"
        FAILED = "failed", "Fallida"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="daily_executions")
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["client", "date"], name="unique_daily_execution"),
        ]
        ordering = ["-date", "-id"]


class DailyDigestItem(models.Model):
    daily_execution = models.ForeignKey(DailyExecution, on_delete=models.CASCADE, related_name="items")
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="digest_items")
    section = models.CharField(max_length=120)
    rank_score = models.FloatField(default=0.0)
    display_title = models.TextField()
    display_lead = models.TextField(blank=True)
    outlets_chips = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["daily_execution", "section"]),
        ]
        ordering = ["rank_score", "id"]


class Correction(models.Model):
    class Scope(models.TextChoices):
        ARTICLE = "article", "Artículo"
        STORY = "story", "Historia"

    scope = models.CharField(max_length=10, choices=Scope.choices)
    target_id = models.PositiveIntegerField()
    field_name = models.CharField(max_length=120)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    explanation = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    apply_to = models.CharField(max_length=40, default="client")

    class Meta:
        indexes = [
            models.Index(fields=["scope", "target_id"]),
        ]

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating:
            TrainingExample.objects.create(
                correction=self,
                scope=self.scope,
                input_features={"field": self.field_name, "old": self.old_value},
                label={"new": self.new_value},
                explanation=self.explanation,
                provenance=f"Correction:{self.pk}",
            )


class TrainingExample(models.Model):
    correction = models.ForeignKey(Correction, on_delete=models.CASCADE, related_name="training_examples")
    scope = models.CharField(max_length=10)
    input_features = models.JSONField(default=dict, blank=True)
    label = models.JSONField(default=dict, blank=True)
    explanation = models.TextField()
    provenance = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["scope", "created_at"]),
        ]


class MetricAggregate(models.Model):
    class EntityType(models.TextChoices):
        PERSONA = "persona", "Persona"
        INSTITUCION = "institucion", "Institución"
        TEMA = "tema", "Tema"

    class Period(models.TextChoices):
        DAY = "day", "Día"
        WEEK = "week", "Semana"
        MONTH = "month", "Mes"

    entity_type = models.CharField(max_length=20, choices=EntityType.choices)
    atlas_id = models.CharField(max_length=120)
    period = models.CharField(max_length=10, choices=Period.choices)
    date_start = models.DateField()
    date_end = models.DateField()
    volume = models.PositiveIntegerField(default=0)
    sentiment_pos = models.PositiveIntegerField(default=0)
    sentiment_neu = models.PositiveIntegerField(default=0)
    sentiment_neg = models.PositiveIntegerField(default=0)
    share_opinion = models.FloatField(default=0.0)
    share_informative = models.FloatField(default=0.0)
    persistence_score = models.FloatField(default=0.0)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type", "atlas_id"]),
            models.Index(fields=["period", "date_start"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "atlas_id", "period", "date_start", "date_end"],
                name="unique_metric_period",
            )
        ]


class BenchmarkSnapshot(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    label = models.CharField(max_length=200)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AuditLog(models.Model):
    event_type = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=120, blank=True)
    entity_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=40, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        ordering = ["-created_at", "-id"]


class JobLog(models.Model):
    job_name = models.CharField(max_length=120)
    status = models.CharField(max_length=40)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
