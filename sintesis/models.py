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
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["template", "id"]

    def clean(self):
        targets = [self.persona_id, self.institucion_id, self.topic_id]
        if sum(1 for value in targets if value) != 1:
            raise ValidationError("Selecciona exactamente un tipo de filtro.")

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
    run_at = models.DateTimeField()
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
        ordering = ["-run_at"]

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
    run_type = models.CharField(max_length=20, choices=RUN_TYPES, default="manual")
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
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
    title = models.CharField(max_length=200)
    summary = models.TextField()
    central_idea = models.TextField(blank=True)
    labels_json = models.JSONField(default=list)
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.run} · {self.title}"

# Create your models here.
