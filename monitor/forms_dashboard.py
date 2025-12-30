from django import forms
from monitor.models import DigestClient, DigestClientConfig
from redpolitica.models import Persona, Institucion


class DigestClientForm(forms.ModelForm):
    class Meta:
        model = DigestClient
        fields = ("name", "slug", "is_active")


class DigestClientConfigForm(forms.ModelForm):
    personas = forms.ModelMultipleChoiceField(
        queryset=Persona.objects.all().order_by("nombre_completo"),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": "12"}),
        help_text="Ctrl/Cmd + click para seleccionar varias."
    )
    instituciones = forms.ModelMultipleChoiceField(
        queryset=Institucion.objects.all().order_by("nombre"),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": "12"}),
        help_text="Ctrl/Cmd + click para seleccionar varias."
    )
    topics_csv = forms.CharField(
        required=False, 
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Temas separados por coma (ej. Seguridad, Elecciones, Movilidad).",
        label="Temas de Interés"
    )

    class Meta:
        model = DigestClientConfig
        fields = ("title", "top_n", "hours", "personas", "instituciones", "topics")
        # topics es el campo JSON del modelo, pero usaremos topics_csv en el form

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Pre-populate topics_csv from JSON field
            topics_list = self.instance.topics or []
            self.fields["topics_csv"].initial = ", ".join(topics_list)

    def clean_topics(self):
        # We don't use this directly for model saving if we exclude it or manually handle it, 
        # but ModelForm expects 'topics' to match model field type if it's in 'fields'.
        # Actually easier approach: exclude 'topics' from Meta fields and save manually.
        pass

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Parse CSV to list
        raw = self.cleaned_data.get("topics_csv", "")
        if raw:
            instance.topics = [t.strip() for t in raw.split(",") if t.strip()]
        else:
            instance.topics = []
        
        if commit:
            instance.save()
            self.save_m2m()
        return instance

# /srv/atlas/monitor/forms_dashboard.py

class OpsForm(forms.Form):
    """
    Formulario único para correr tareas operativas (ingesta/pipeline) desde dashboard.
    Cada acción usa un subset de campos.
    """
    action = forms.ChoiceField(
        choices=[
            ("fetch_sources", "1) Traer RSS (fetch_sources)"),
            ("fetch_article_bodies", "2) Completar body (fetch_article_bodies)"),
            ("embed_articles", "3) Embeddings (embed_articles)"),
            ("cluster_articles_ai", "4) Clustering AI (cluster_articles_ai)"),
            ("link_entities", "5) Link entidades (link_entities)"),
            ("run_monitor_pipeline", "🔥 6) FULL PIPELINE 2.0 (Orquestador)"),
            ("create_digest_summary", "7) Generar Sintesis IA (Solo digest)"),
        ],
        required=True,
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Acción",
    )

    # Comunes
    limit = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=5000,
        initial=200,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        label="Limit",
        help_text="Máximo de items a procesar (cuando aplique).",
    )

    # fetch_sources
    source_id = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        label="source-id (opcional)",
        help_text="Si lo pones, solo trae un Source id.",
    )

    # fetch_article_bodies
    force = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(),
        label="force (solo bodies)",
        help_text="Si activas force, vuelve a bajar body aunque ya exista.",
    )

    # cluster_articles_ai / link_atlas_entities
    hours = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=24 * 60,
        initial=72,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        label="hours",
        help_text="Ventana en horas (cuando aplique).",
    )

    threshold = forms.FloatField(
        required=False,
        min_value=0.1,
        max_value=0.99,
        initial=0.86,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        label="threshold (solo clustering)",
        help_text="Umbral de similitud para clustering (ej. 0.86).",
    )

    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(),
        label="dry-run (solo clustering)",
        help_text="Si activas dry-run, no crea clusters/mentions, solo calcula candidatos.",
    )

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")

        # Defaults seguros por acción (si el usuario deja vacío)
        if action == "fetch_sources":
            if not cleaned.get("limit"):
                cleaned["limit"] = 50

        if action == "fetch_article_bodies":
            if not cleaned.get("limit"):
                cleaned["limit"] = 80

        if action == "embed_articles":
            if not cleaned.get("limit"):
                cleaned["limit"] = 80

        if action == "cluster_articles_ai":
            if not cleaned.get("limit"):
                cleaned["limit"] = 400
            if not cleaned.get("hours"):
                cleaned["hours"] = 72
            if cleaned.get("threshold") is None:
                cleaned["threshold"] = 0.86

        if action == "link_entities":
            if not cleaned.get("limit"):
                cleaned["limit"] = 2000
            if not cleaned.get("hours"):
                cleaned["hours"] = 120
        
        if action == "run_monitor_pipeline":
             if not cleaned.get("hours"):
                cleaned["hours"] = 24
             if not cleaned.get("limit"):
                 cleaned["limit"] = 500

        return cleaned
