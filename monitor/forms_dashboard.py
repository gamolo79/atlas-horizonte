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

    class Meta:
        model = DigestClientConfig
        fields = ("title", "top_n", "hours", "personas", "instituciones")

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
        help_text="Si lo pones, solo trae un MediaSource id.",
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

        return cleaned
