from django.contrib import admin

from monitor import models


@admin.register(models.IngestRun)
class IngestRunAdmin(admin.ModelAdmin):
    list_display = ("action", "status", "started_at", "finished_at")
    list_filter = ("status", "action")


@admin.register(models.MediaOutlet)
class MediaOutletAdmin(admin.ModelAdmin):
    list_display = ("name", "site_url")
    search_fields = ("name",)


@admin.register(models.MediaSource)
class MediaSourceAdmin(admin.ModelAdmin):
    list_display = ("media_outlet", "source_type", "url", "is_active", "last_fetched_at")
    list_filter = ("source_type", "is_active")
    search_fields = ("url",)


@admin.register(models.Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "outlet", "published_at", "pipeline_status")
    list_filter = ("pipeline_status", "outlet")
    search_fields = ("title", "url")


@admin.register(models.StoryCluster)
class StoryClusterAdmin(admin.ModelAdmin):
    list_display = ("headline", "run", "confidence", "created_at")
    list_filter = ("run",)


@admin.register(models.StoryMention)
class StoryMentionAdmin(admin.ModelAdmin):
    list_display = ("cluster", "article", "media_outlet", "match_score")
    list_filter = ("media_outlet",)
