from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from monitor.models import Article
from redpolitica.models import Institucion, Persona, Topic


class SynthesisClient(models.Model):
    name = models.CharField(max_length=255)
    persona = models.ForeignKey(
        Persona,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sintesis_clientes",
        help_text="Persona de Atlas asociada al cliente (opcional).",
    )
    institucion = models.ForeignKey(
        Institucion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sintesis_clientes",
        help_text="Institución de Atlas asociada al cliente (opcional).",
    )
    description = models.TextField(blank=True)
    keyword_tags = models.JSONField(
        default=list,
        help_text="Lista de palabras o etiquetas clave para filtrar historias.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        if not self.persona and not self.institucion:
            raise ValidationError("Debes asociar una persona o institución.")

    def __str__(self) -> str:
        return self.name


class SynthesisClientInterest(models.Model):
    GROUP_CHOICES = [
        ("priority", "Prioritario"),
        ("general", "General"),
    ]

    client = models.ForeignKey(
        SynthesisClient,
        on_delete=models.CASCADE,
        related_name="interests",
    )
    persona = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_intereses",
    )
    institucion = models.ForeignKey(
        Institucion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_intereses",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_intereses",
    )
    interest_group = models.CharField(
        max_length=20,
        choices=GROUP_CHOICES,
        default="general",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["client", "id"]

    def clean(self):
        targets = [self.persona_id, self.institucion_id, self.topic_id]
        if sum(1 for value in targets if value) != 1:
            raise ValidationError("Selecciona exactamente un tipo de interés.")

    def __str__(self) -> str:
        if self.persona_id:
            return f"{self.client} · {self.persona}"
        if self.institucion_id:
            return f"{self.client} · {self.institucion}"
        return f"{self.client} · {self.topic}"


class SynthesisSectionTemplate(models.Model):
    GROUP_BY_CHOICES = [
        ("story", "Historia"),
        ("institution", "Institución"),
    ]
    SECTION_TYPES = [
        ("custom", "Personalizada"),
        ("by_institution", "Temas por institución"),
    ]

    client = models.ForeignKey(
        SynthesisClient,
        on_delete=models.CASCADE,
        related_name="section_templates",
    )
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)
    group_by = models.CharField(max_length=20, choices=GROUP_BY_CHOICES, default="story")
    is_active = models.BooleanField(default=True)
    section_type = models.CharField(
        max_length=30,
        choices=SECTION_TYPES,
        default="custom",
    )
    section_prompt = models.TextField(blank=True)
    contract_keywords_positive = models.JSONField(
        default=list,
        blank=True,
        help_text="Palabras clave positivas para el contrato de sección.",
    )
    contract_keywords_negative = models.JSONField(
        default=list,
        blank=True,
        help_text="Palabras clave negativas para excluir artículos.",
    )
    contract_min_score = models.FloatField(
        default=0.6,
        help_text="Score mínimo para aceptar artículos sin mención fuerte.",
    )
    contract_min_mentions = models.PositiveIntegerField(
        default=2,
        help_text="Número mínimo de menciones totales si no hay mención fuerte.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.client} · {self.title}"


class SynthesisSectionFilter(models.Model):
    template = models.ForeignKey(
        SynthesisSectionTemplate,
        on_delete=models.CASCADE,
        related_name="filters",
    )
    persona = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_section_filters",
    )
    institucion = models.ForeignKey(
        Institucion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_section_filters",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sintesis_section_filters",
    )
    keywords = models.CharField(
        max_length=500,
        blank=True,
        help_text="Lista de palabras clave o etiquetas separadas por comas.",
    )
    keywords_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["template", "id"]

    def clean(self):
        targets = [self.persona_id, self.institucion_id, self.topic_id, self.keywords]
        if not any(targets):
            raise ValidationError("Debes especificar al menos un criterio de filtro.")

    def __str__(self) -> str:
        if self.persona_id:
            return f"{self.template} · {self.persona}"
        if self.institucion_id:
            return f"{self.template} · {self.institucion}"
        return f"{self.template} · {self.topic}"


class SynthesisSchedule(models.Model):
    client = models.ForeignKey(
        SynthesisClient,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    name = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=80, default="America/Mexico_City")
    run_time = models.TimeField()
    window_start_time = models.TimeField()
    window_end_time = models.TimeField()
    days_of_week = models.JSONField(default=list)
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sintesis_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-next_run_at"]

    def __str__(self) -> str:
        label = self.name or "Programación"
        return f"{label} · {self.client}"


class SynthesisRun(models.Model):
    RUN_TYPES = [
        ("manual", "Manual"),
        ("scheduled", "Programado"),
    ]
    STATUS_CHOICES = [
        ("queued", "En cola"),
        ("running", "En ejecución"),
        ("completed", "Completado"),
        ("failed", "Fallido"),
    ]

    client = models.ForeignKey(
        SynthesisClient,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    schedule = models.ForeignKey(
        SynthesisSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    parent_run = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )
    version = models.PositiveIntegerField(default=1)
    run_type = models.CharField(max_length=20, choices=RUN_TYPES, default="manual")
    regeneration_scope = models.CharField(max_length=20, blank=True)
    regenerated_template_id = models.IntegerField(null=True, blank=True)
    review_text = models.TextField(blank=True)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    output_count = models.PositiveIntegerField(default=0)
    log_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    html_snapshot = models.TextField(blank=True)
    stats_json = models.JSONField(default=dict, blank=True)
    pdf_file = models.FileField(
        upload_to="sintesis/pdfs/%Y/%m/",
        null=True,
        blank=True,
    )
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Síntesis #{self.pk} · {self.client}"


class SynthesisStory(models.Model):
    client = models.ForeignKey(
        SynthesisClient,
        on_delete=models.CASCADE,
        related_name="stories",
    )
    run = models.ForeignKey(
        SynthesisRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stories",
    )
    run_section = models.ForeignKey(
        "SynthesisRunSection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stories",
    )
    story_fingerprint = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    central_idea = models.TextField(blank=True)
    labels_json = models.JSONField(default=list)
    group_signals_json = models.JSONField(default=list, blank=True)
    article_count = models.PositiveIntegerField(default=0)
    unique_sources_count = models.PositiveIntegerField(default=0)
    source_names_json = models.JSONField(default=list, blank=True)
    type_counts_json = models.JSONField(default=dict, blank=True)
    sentiment_counts_json = models.JSONField(default=dict, blank=True)
    group_label = models.CharField(max_length=255, blank=True)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "story_fingerprint"],
                name="unique_story_fingerprint_per_run",
            )
        ]

    def __str__(self) -> str:
        return self.title


class SynthesisStoryArticle(models.Model):
    story = models.ForeignKey(
        SynthesisStory,
        on_delete=models.CASCADE,
        related_name="story_articles",
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="sintesis_items",
    )
    source_name = models.CharField(max_length=255)
    source_url = models.URLField(max_length=1000)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        unique_together = ("story", "article")

    def __str__(self) -> str:
        return f"{self.story} · {self.source_name}"


class SynthesisRunSection(models.Model):
    run = models.ForeignKey(
        SynthesisRun,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    template = models.ForeignKey(
        SynthesisSectionTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="run_sections",
    )
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=1)
    group_by = models.CharField(
        max_length=20,
        choices=SynthesisSectionTemplate.GROUP_BY_CHOICES,
        default="story",
    )
    stats_json = models.JSONField(default=dict, blank=True)
    review_text = models.TextField(blank=True)
    prompt_snapshot = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.run} · {self.title}"


class SynthesisSectionRoutingResult(models.Model):
    run = models.ForeignKey(
        SynthesisRun,
        on_delete=models.CASCADE,
        related_name="routing_results",
    )
    template = models.ForeignKey(
        SynthesisSectionTemplate,
        on_delete=models.CASCADE,
        related_name="routing_results",
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="routing_results",
    )
    is_included = models.BooleanField(default=False)
    score = models.FloatField(default=0.0)
    scores_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["run", "template", "article"]),
        ]

    def __str__(self) -> str:
        return f"Routing {self.article_id} -> {self.template_id}"


class SynthesisArticleMentionStrength(models.Model):
    STRENGTH_CHOICES = [
        ("strong", "Fuerte"),
        ("weak", "Débil"),
    ]

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="mention_strengths",
    )
    target_type = models.CharField(max_length=20)
    target_id = models.IntegerField()
    target_name = models.CharField(max_length=255)
    strength = models.CharField(max_length=10, choices=STRENGTH_CHOICES)
    positions_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["article", "target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.target_name} ({self.strength})"


class SynthesisArticleEmbedding(models.Model):
    article = models.OneToOneField(
        Article,
        on_delete=models.CASCADE,
        related_name="embedding_cache",
    )
    canonical_hash = models.CharField(max_length=64, db_index=True)
    canonical_text = models.TextField()
    embedding_json = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Embedding {self.article_id}"


class SynthesisArticleDedup(models.Model):
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="dedupe_entries",
    )
    run = models.ForeignKey(
        SynthesisRun,
        on_delete=models.CASCADE,
        related_name="dedupe_entries",
    )
    dedup_key = models.CharField(max_length=128, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    duplicate_of = models.ForeignKey(
        Article,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deduped_children",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Dedupe {self.article_id}"


class SynthesisCluster(models.Model):
    run = models.ForeignKey(
        SynthesisRun,
        on_delete=models.CASCADE,
        related_name="clusters",
    )
    template = models.ForeignKey(
        SynthesisSectionTemplate,
        on_delete=models.CASCADE,
        related_name="clusters",
    )
    centroid_json = models.JSONField(default=list)
    top_entities_json = models.JSONField(default=list, blank=True)
    top_tags_json = models.JSONField(default=list, blank=True)
    time_start = models.DateTimeField()
    time_end = models.DateTimeField()
    story_key = models.CharField(max_length=128, blank=True)
    story_title = models.CharField(max_length=255, blank=True)
    story_summary = models.TextField(blank=True)
    key_entities_json = models.JSONField(default=list, blank=True)
    stats_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["run", "template"]),
        ]

    def __str__(self) -> str:
        return f"Cluster {self.pk}"


class SynthesisClusterMember(models.Model):
    cluster = models.ForeignKey(
        SynthesisCluster,
        on_delete=models.CASCADE,
        related_name="members",
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="cluster_memberships",
    )
    similarity = models.FloatField(default=0.0)
    matched_signals_json = models.JSONField(default=list, blank=True)
    is_strong_match = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("cluster", "article")

    def __str__(self) -> str:
        return f"{self.cluster_id} · {self.article_id}"


class SynthesisClusterLabelCache(models.Model):
    story_key = models.CharField(max_length=128)
    label_date = models.DateField()
    payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("story_key", "label_date")

    def __str__(self) -> str:
        return f"{self.story_key} · {self.label_date}"

# Create your models here.
