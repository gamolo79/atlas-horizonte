from django.contrib import admin

from .models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisRun,
    SynthesisSchedule,
    SynthesisStory,
    SynthesisStoryArticle,
)


@admin.register(SynthesisClient)
class SynthesisClientAdmin(admin.ModelAdmin):
    list_display = ("name", "persona", "institucion", "is_active", "updated_at")
    search_fields = ("name", "persona__nombre_completo", "institucion__nombre")
    list_filter = ("is_active",)


@admin.register(SynthesisClientInterest)
class SynthesisClientInterestAdmin(admin.ModelAdmin):
    list_display = ("client", "persona", "institucion", "topic", "created_at")
    search_fields = (
        "client__name",
        "persona__nombre_completo",
        "institucion__nombre",
        "topic__name",
    )


@admin.register(SynthesisSchedule)
class SynthesisScheduleAdmin(admin.ModelAdmin):
    list_display = ("client", "name", "run_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("client__name", "name")


@admin.register(SynthesisRun)
class SynthesisRunAdmin(admin.ModelAdmin):
    list_display = ("client", "run_type", "status", "started_at", "finished_at")
    list_filter = ("run_type", "status")
    search_fields = ("client__name",)


@admin.register(SynthesisStory)
class SynthesisStoryAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "article_count", "created_at")
    search_fields = ("title", "client__name")


@admin.register(SynthesisStoryArticle)
class SynthesisStoryArticleAdmin(admin.ModelAdmin):
    list_display = ("story", "source_name", "published_at")
    search_fields = ("story__title", "source_name")
