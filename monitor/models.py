from django.conf import settings
from django.db import models


class Source(models.Model):
    SOURCE_TYPES = [
        ("rss", "RSS"),
        ("sitemap", "Sitemap"),
        ("scrape", "Scrape"),
    ]
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("error", "Error"),
    ]

    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES)
    url = models.URLField(max_length=1000)
    is_active = models.BooleanField(default=True)
    frequency_minutes = models.PositiveIntegerField(default=60)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ok")
    last_error_text = models.TextField(blank=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)
    last_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    last_new_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    STATUS_CHOICES = [
        ("new", "Nueva"),
        ("processed", "Procesada"),
        ("error", "Error"),
    ]

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="articles")
    url = models.URLField(max_length=1000, unique=True)
    title = models.CharField(max_length=500)
    published_at = models.DateTimeField(null=True, blank=True)
    author = models.CharField(max_length=255, blank=True)
    raw_html = models.TextField(blank=True)
    text = models.TextField()
    meta_description = models.TextField(blank=True)
    meta_keywords = models.TextField(blank=True)
    extracted_tags_json = models.JSONField(null=True, blank=True)
    language = models.CharField(max_length=20, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    error_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-published_at", "-fetched_at"]

    def __str__(self) -> str:
        return self.title


class Classification(models.Model):
    ARTICLE_TYPES = [
        ("informativo", "Informativo"),
        ("opinion", "Opinión"),
    ]

    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="classification")
    central_idea = models.TextField()
    article_type = models.CharField(max_length=20, choices=ARTICLE_TYPES)
    labels_json = models.JSONField(default=list)
    model_name = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_editor_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Clasificación #{self.pk}"


class Mention(models.Model):
    TARGET_TYPES = [
        ("persona", "Persona"),
        ("institucion", "Institución"),
        ("tema", "Tema"),
    ]
    SENTIMENT_CHOICES = [
        ("positivo", "Positivo"),
        ("neutro", "Neutro"),
        ("negativo", "Negativo"),
    ]

    classification = models.ForeignKey(
        Classification, on_delete=models.CASCADE, related_name="mentions"
    )
    target_type = models.CharField(max_length=20, choices=TARGET_TYPES)
    target_id = models.IntegerField()
    target_name = models.CharField(max_length=255)
    sentiment = models.CharField(max_length=20, choices=SENTIMENT_CHOICES)
    confidence = models.FloatField()

    class Meta:
        ordering = ["-confidence"]

    def __str__(self) -> str:
        return f"{self.target_name} ({self.get_target_type_display()})"


class EditorialReview(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="reviews")
    before_json = models.JSONField()
    after_json = models.JSONField()
    reason_text = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Revisión #{self.pk}"


class BatchSuggestion(models.Model):
    review = models.ForeignKey(EditorialReview, on_delete=models.CASCADE, related_name="batch_suggestions")
    query_json = models.JSONField()
    affected_count = models.PositiveIntegerField(default=0)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"Lote #{self.pk}"


class ProcessRun(models.Model):
    RUN_TYPES = [
        ("ingest", "Ingesta"),
        ("classify", "Clasificación"),
        ("all", "Pipeline completo"),
    ]
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("error", "Error"),
        ("running", "En ejecución"),
    ]

    run_type = models.CharField(max_length=20, choices=RUN_TYPES)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    notes = models.TextField(blank=True)
    log_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Proceso #{self.pk}"
