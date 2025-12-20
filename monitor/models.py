from django.db import models
from django.conf import settings


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


class Article(models.Model):
    media_outlet = models.ForeignKey(MediaOutlet, on_delete=models.CASCADE)
    source = models.ForeignKey(MediaSource, null=True, blank=True, on_delete=models.SET_NULL)

    url = models.URLField(max_length=1000, unique=True)

    title = models.TextField()
    lead = models.TextField(blank=True)
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=60, blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    fetched_at = models.DateTimeField(null=True, blank=True)
    authors = models.CharField(max_length=400, blank=True)
    section = models.CharField(max_length=200, blank=True)

    published_at = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=10, default="es")

    entities_extracted = models.JSONField(default=dict, blank=True)
    quality_score = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["media_outlet", "published_at"]),
        ]
        ordering = ["-published_at", "-id"]

    def __str__(self):
        return self.title[:80]


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

class Digest(models.Model):
    """
    Síntesis editorial diaria (HTML).
    """
    date = models.DateField()
    title = models.CharField(max_length=200)
    html_content = models.TextField()
    json_content = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("date", "title")
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} · {self.title}"

class DigestSection(models.Model):
    class SectionType(models.TextChoices):
        PRIORITY = "priority", "Prioritaria"
        BY_PARENT = "by_parent", "Por institución padre"
        GENERAL = "general", "General"

    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="sections")
    section_type = models.CharField(max_length=20, choices=SectionType.choices, default=SectionType.GENERAL)
    label = models.CharField(max_length=200)  # ej: "IEEQ", "Poder Ejecutivo"
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.digest.date} · {self.label}"


class DigestItem(models.Model):
    section = models.ForeignKey(DigestSection, on_delete=models.CASCADE, related_name="items")
    cluster = models.ForeignKey(StoryCluster, on_delete=models.CASCADE)

    order = models.PositiveIntegerField(default=0)

    # por si quieres sobreescribir el titular/lead para la síntesis
    custom_headline = models.TextField(blank=True)
    custom_lead = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["section", "cluster"], name="uniq_section_cluster"),
        ]

class ContentClassification(models.Model):
    class ContentType(models.TextChoices):
        INFORMATIVE = "informative", "Informativo"
        OPINION = "opinion", "Opinión"

    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="content_classification")
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    confidence = models.CharField(max_length=10, default="media")  # alta/media/baja
    justification = models.TextField(blank=True)
    model_meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.article_id} · {self.content_type}"


class ArticleSentiment(models.Model):
    class Sentiment(models.TextChoices):
        POSITIVE = "positivo", "Positivo"
        NEUTRAL = "neutro", "Neutro"
        NEGATIVE = "negativo", "Negativo"

    class Confidence(models.TextChoices):
        HIGH = "alta", "Alta"
        MEDIUM = "media", "Media"
        LOW = "baja", "Baja"

    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="sentiment")
    sentiment = models.CharField(max_length=10, choices=Sentiment.choices)
    confidence = models.CharField(max_length=10, choices=Confidence.choices, default=Confidence.MEDIUM)
    justification = models.TextField(blank=True)
    model_meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.article_id} · {self.sentiment}"


# --- Atlas ↔ Monitor bridge (aliases + mentions) ---

from django.db import models
from django.utils import timezone

from redpolitica.models import Persona, Institucion


class PersonaAlias(models.Model):
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=255, db_index=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("persona", "alias")
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} → {self.persona}"


class InstitucionAlias(models.Model):
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=255, db_index=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("institucion", "alias")
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} → {self.institucion}"


class ArticlePersonaMention(models.Model):
    article = models.ForeignKey("monitor.Article", on_delete=models.CASCADE, related_name="person_mentions")
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="article_mentions")
    matched_alias = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("article", "persona")
        ordering = ["-created_at"]


class ArticleInstitucionMention(models.Model):
    article = models.ForeignKey("monitor.Article", on_delete=models.CASCADE, related_name="institution_mentions")
    institucion = models.ForeignKey(Institucion, on_delete=models.CASCADE, related_name="article_mentions")
    matched_alias = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("article", "institucion")
        ordering = ["-created_at"]

class DigestClient(models.Model):
    """
    Un 'cliente' (AMEQ, Felifer, etc.) con watchlist de personas/instituciones.
    """
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="digest_clients"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class DigestClientConfig(models.Model):
    """
    Configuración para generar el digest (top, hours, watchlist).
    """
    client = models.OneToOneField(DigestClient, on_delete=models.CASCADE, related_name="config")

    title = models.CharField(max_length=255, default="Síntesis diaria (cliente)")
    top_n = models.PositiveIntegerField(default=7)
    hours = models.PositiveIntegerField(default=48)

    personas = models.ManyToManyField("redpolitica.Persona", blank=True, related_name="digest_client_configs")
    instituciones = models.ManyToManyField("redpolitica.Institucion", blank=True, related_name="digest_client_configs")

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Config: {self.client.name}"
