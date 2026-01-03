import json

from django import forms

from .models import (
    Institucion,
    InstitutionTopic,
    Persona,
    PersonTopicManual,
    Topic,
)


class AliasesField(forms.CharField):
    def clean(self, value):
        value = super().clean(value)
        if not value:
            return []
        stripped_value = value.strip()
        if stripped_value.startswith("["):
            try:
                parsed = json.loads(stripped_value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                cleaned = [str(alias).strip() for alias in parsed if str(alias).strip()]
                return cleaned
        return [alias.strip() for alias in value.split(",") if alias.strip()]


class AliasesFormMixin:
    aliases = AliasesField(
        required=False,
        help_text="Lista de aliases separados por comas.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, "aliases", None):
            self.initial.setdefault("aliases", self.instance.aliases)

    def clean_aliases(self):
        aliases_text = self.cleaned_data.get("aliases", "")
        if not aliases_text:
            return ""
        cleaned_aliases = [
            alias.strip()
            for alias in aliases_text.split(",")
            if alias.strip()
        ]
        return ", ".join(cleaned_aliases)


class PersonaForm(AliasesFormMixin, forms.ModelForm):
    class Meta:
        model = Persona
        fields = "__all__"


class InstitucionForm(AliasesFormMixin, forms.ModelForm):
    class Meta:
        model = Institucion
        fields = "__all__"


class TopicForm(AliasesFormMixin, forms.ModelForm):
    class Meta:
        model = Topic
        fields = ["name", "parent", "topic_kind", "status", "description", "aliases"]


class InstitutionTopicForm(forms.ModelForm):
    class Meta:
        model = InstitutionTopic
        fields = ["topic", "role", "note"]


class PersonTopicManualForm(forms.ModelForm):
    class Meta:
        model = PersonTopicManual
        fields = ["topic", "role", "note"]
