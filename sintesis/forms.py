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

    class Meta:
        model = SynthesisSectionTemplate
        fields = ["title", "order", "group_by", "section_type", "is_active", "keywords"]

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
            SynthesisSectionFilter.objects.create(template=instance, keywords=raw_keywords.strip())


class SynthesisScheduleForm(forms.ModelForm):
    class Meta:
        model = SynthesisSchedule
        fields = ["client", "name", "run_at", "is_active"]
        widgets = {
            "run_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class SynthesisRunForm(forms.Form):
    client = forms.ModelChoiceField(queryset=SynthesisClient.objects.all())
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
