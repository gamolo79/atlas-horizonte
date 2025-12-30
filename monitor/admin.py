from django.contrib import admin

from monitor import models


@admin.register(models.Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "outlet", "source_type", "is_active", "last_fetched_at")
    search_fields = ("name", "url", "outlet")
    list_filter = ("source_type", "is_active")


@admin.register(models.Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "outlet", "published_at", "pipeline_status")
    search_fields = ("title", "url")
    list_filter = ("pipeline_status", "outlet")


@admin.register(models.ClassificationRun)
class ClassificationRunAdmin(admin.ModelAdmin):
    list_display = ("article", "model_name", "status", "started_at", "finished_at")
    list_filter = ("status", "model_name")


@admin.register(models.Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("title_base", "status", "time_window_start", "time_window_end")
    list_filter = ("status",)


@admin.register(models.Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name", "slug")


@admin.register(models.MetricAggregate)
class MetricAggregateAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "atlas_id", "period", "date_start", "volume")
    list_filter = ("entity_type", "period")


@admin.register(models.Correction)
class CorrectionAdmin(admin.ModelAdmin):
    list_display = ("scope", "target_id", "field_name", "created_at")
    list_filter = ("scope",)


admin.site.register(models.AuditLog)
admin.site.register(models.DailyExecution)
admin.site.register(models.DailyDigestItem)
admin.site.register(models.EditorialTag)
admin.site.register(models.TagLink)
admin.site.register(models.TopicLink)
admin.site.register(models.ActorLink)
admin.site.register(models.ArticleVersion)
admin.site.register(models.DecisionTrace)
admin.site.register(models.Extraction)
admin.site.register(models.TrainingExample)
admin.site.register(models.JobLog)
