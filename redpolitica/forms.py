from django import forms

from .models import InstitutionTopic, PersonTopicManual, Topic


class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = [
            "name",
            "slug",
            "description",
            "parent",
            "topic_kind",
            "status",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "search-input"}),
            "slug": forms.TextInput(attrs={"class": "search-input"}),
            "description": forms.Textarea(attrs={"class": "search-input", "rows": 4}),
            "parent": forms.Select(attrs={"class": "search-input"}),
            "topic_kind": forms.Select(attrs={"class": "search-input"}),
            "status": forms.Select(attrs={"class": "search-input"}),
        }


class InstitutionTopicForm(forms.ModelForm):
    class Meta:
        model = InstitutionTopic
        fields = [
            "institution",
            "role",
            "note",
            "valid_from",
            "valid_to",
        ]
        widgets = {
            "institution": forms.Select(attrs={"class": "search-input"}),
            "role": forms.TextInput(attrs={"class": "search-input"}),
            "note": forms.Textarea(attrs={"class": "search-input", "rows": 3}),
            "valid_from": forms.DateInput(attrs={"type": "date", "class": "search-input"}),
            "valid_to": forms.DateInput(attrs={"type": "date", "class": "search-input"}),
        }


class PersonTopicManualForm(forms.ModelForm):
    class Meta:
        model = PersonTopicManual
        fields = [
            "person",
            "role",
            "note",
            "source_url",
        ]
        widgets = {
            "person": forms.Select(attrs={"class": "search-input"}),
            "role": forms.TextInput(attrs={"class": "search-input"}),
            "note": forms.Textarea(attrs={"class": "search-input", "rows": 3}),
            "source_url": forms.URLInput(attrs={"class": "search-input"}),
        }
