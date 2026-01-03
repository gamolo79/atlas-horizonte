from django import forms

from .models import Institucion, Persona


class AliasesFormMixin:
    aliases = forms.CharField(
        required=False,
        help_text="Lista de aliases separados por comas.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, "aliases", None):
            self.initial.setdefault("aliases", ", ".join(self.instance.aliases))

    def clean_aliases(self):
        aliases_text = self.cleaned_data.get("aliases", "")
        if not aliases_text:
            return []
        return [
            alias.strip()
            for alias in aliases_text.split(",")
            if alias.strip()
        ]


class PersonaForm(AliasesFormMixin, forms.ModelForm):
    class Meta:
        model = Persona
        fields = "__all__"


class InstitucionForm(AliasesFormMixin, forms.ModelForm):
    class Meta:
        model = Institucion
        fields = "__all__"
