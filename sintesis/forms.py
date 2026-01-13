from django import forms

from redpolitica.models import Institucion, Persona, Topic

from .models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisSchedule,
    SynthesisSectionFilter,
    SynthesisSectionTemplate,
)


class SynthesisClientForm(forms.ModelForm):
    keyword_tags = forms.CharField(
        required=False,
        help_text="Separar con comas para etiquetas clave.",
        widget=forms.TextInput(attrs={"placeholder": "salud, justicia, movilidad"}),
    )

    class Meta:
        model = SynthesisClient
        fields = ["name", "persona", "institucion", "description", "keyword_tags", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["keyword_tags"].initial = self._format_keyword_tags()

    def clean_keyword_tags(self):
        raw = self.cleaned_data.get("keyword_tags", "")
        if isinstance(raw, list):
            return raw
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _format_keyword_tags(self):
        value = self.instance.keyword_tags
        if isinstance(value, list):
            return ", ".join(value)
        return value


class SynthesisClientInterestForm(forms.ModelForm):
    class Meta:
        model = SynthesisClientInterest
        fields = ["persona", "institucion", "topic", "interest_group", "note"]


class SynthesisSectionTemplateForm(forms.ModelForm):
    personas = forms.ModelMultipleChoiceField(
        queryset=Persona.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
    )
    instituciones = forms.ModelMultipleChoiceField(
        queryset=Institucion.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
    )
    topics = forms.ModelMultipleChoiceField(
        queryset=Topic.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
    )
    keywords = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "palabras, clave, separadas, por, comas"}),
        help_text="Lista de palabras para filtrar (además de personas/instituciones).",
    )
    section_prompt = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Instrucciones opcionales para esta sección"}),
    )

    class Meta:
        model = SynthesisSectionTemplate
        fields = [
            "title",
            "order",
            "group_by",
            "section_type",
            "is_active",
            "section_prompt",
            "keywords",
        ]

    def __init__(self, *args, **kwargs):
        persona_queryset = kwargs.pop("persona_queryset", None)
        institucion_queryset = kwargs.pop("institucion_queryset", None)
        topic_queryset = kwargs.pop("topic_queryset", None)
        super().__init__(*args, **kwargs)
        self.fields["personas"].queryset = persona_queryset or self.fields["personas"].queryset.none()
        self.fields["instituciones"].queryset = (
            institucion_queryset or self.fields["instituciones"].queryset.none()
        )
        self.fields["topics"].queryset = topic_queryset or self.fields["topics"].queryset.none()

        # Pre-fill keywords if editing
        if self.instance.pk:
            # Join all keywords from filters that have them
            keyword_filters = self.instance.filters.exclude(keywords="").values_list("keywords", flat=True)
            self.fields["keywords"].initial = ", ".join(keyword_filters)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self._save_filters(instance)
        return instance

    def save_filters(self, instance):
        self._save_filters(instance)

    def _save_filters(self, instance):
        SynthesisSectionFilter.objects.filter(template=instance).delete()
        for persona in self.cleaned_data.get("personas") or []:
            SynthesisSectionFilter.objects.create(template=instance, persona=persona)
        for institucion in self.cleaned_data.get("instituciones") or []:
            SynthesisSectionFilter.objects.create(template=instance, institucion=institucion)
        for topic in self.cleaned_data.get("topics") or []:
            SynthesisSectionFilter.objects.create(template=instance, topic=topic)
        
        # Save keywords
        raw_keywords = self.cleaned_data.get("keywords", "")
        if raw_keywords.strip():
            keywords_list = [item.strip() for item in raw_keywords.split(",") if item.strip()]
            SynthesisSectionFilter.objects.create(
                template=instance,
                keywords=raw_keywords.strip(),
                keywords_json=keywords_list,
            )


class SynthesisScheduleForm(forms.ModelForm):
    days_of_week = forms.MultipleChoiceField(
        choices=[
            (0, "Lun"),
            (1, "Mar"),
            (2, "Mié"),
            (3, "Jue"),
            (4, "Vie"),
            (5, "Sáb"),
            (6, "Dom"),
        ],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = SynthesisSchedule
        fields = [
            "client",
            "name",
            "timezone",
            "run_time",
            "window_start_time",
            "window_end_time",
            "days_of_week",
            "is_active",
        ]
        widgets = {
            "run_time": forms.TimeInput(attrs={"type": "time"}),
            "window_start_time": forms.TimeInput(attrs={"type": "time"}),
            "window_end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean_days_of_week(self):
        raw = self.cleaned_data.get("days_of_week") or []
        return [int(day) for day in raw]


class SynthesisRunForm(forms.Form):
    client = forms.ModelChoiceField(queryset=SynthesisClient.objects.all())
    window_start = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    window_end = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
