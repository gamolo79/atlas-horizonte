from django import forms

from .models import SynthesisClient, SynthesisClientInterest, SynthesisSchedule


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
        fields = ["persona", "institucion", "topic", "note"]


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
