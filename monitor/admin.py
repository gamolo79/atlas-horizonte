from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Article,
    BatchSuggestion,
    Classification,
    EditorialReview,
    Mention,
    ProcessRun,
    Source,
)


@admin.action(description="Activar fuentes seleccionadas")
def activate_sources(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Desactivar fuentes seleccionadas")
def deactivate_sources(modeladmin, request, queryset):
    queryset.update(is_active=False)


class MentionInline(admin.TabularInline):
    model = Mention
    extra = 0


class ClassificationInline(admin.StackedInline):
    model = Classification
    extra = 0
    show_change_link = True


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "source_type",
        "url",
        "is_active",
        "frequency_minutes",
        "last_status",
        "last_run_at",
        "last_new_count",
    )
    list_filter = ("source_type", "is_active", "last_status")
    search_fields = ("name", "url")
    actions = [activate_sources, deactivate_sources]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "source",
        "published_at",
        "status",
        "original_link",
    )
    list_filter = ("status", "source")
    search_fields = ("title", "url")
    inlines = [ClassificationInline]

    @admin.display(description="URL")
    def original_link(self, obj):
        return format_html('<a href="{url}" target="_blank">Abrir</a>', url=obj.url)


@admin.register(Classification)
class ClassificationAdmin(admin.ModelAdmin):
    list_display = ("article", "article_type", "model_name", "created_at", "is_editor_locked")
    list_filter = ("article_type", "is_editor_locked")
    search_fields = ("article__title", "article__url")
    inlines = [MentionInline]


@admin.register(Mention)
class MentionAdmin(admin.ModelAdmin):
    list_display = ("classification", "target_type", "target_name", "sentiment", "confidence")
    list_filter = ("target_type", "sentiment")
    search_fields = ("target_name",)


@admin.register(EditorialReview)
class EditorialReviewAdmin(admin.ModelAdmin):
    list_display = ("article", "created_by", "created_at")
    search_fields = ("article__title", "article__url", "reason_text")


@admin.register(BatchSuggestion)
class BatchSuggestionAdmin(admin.ModelAdmin):
    list_display = ("review", "affected_count", "applied_at")


@admin.register(ProcessRun)
class ProcessRunAdmin(admin.ModelAdmin):
    list_display = ("run_type", "status", "started_at", "finished_at")
    list_filter = ("run_type", "status")
    search_fields = ("notes", "log_text")
