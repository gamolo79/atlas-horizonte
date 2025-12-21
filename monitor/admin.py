from django.contrib import admin
from django.db import transaction

from .models import (
    Article,
    ArticleInstitucionMention,
    ArticlePersonaMention,
    ArticleSentiment,
    ContentClassification,
    Digest,
    DigestClient,
    DigestClientConfig,
    IngestRun,
    MediaOutlet,
    MediaSource,
    StoryCluster,
    StoryMention,
)


def _purge_articles(queryset):
    article_ids = list(queryset.values_list("id", flat=True))
    if not article_ids:
        return
    StoryCluster.objects.filter(base_article_id__in=article_ids).update(base_article=None)
    StoryMention.objects.filter(article_id__in=article_ids).delete()
    ArticlePersonaMention.objects.filter(article_id__in=article_ids).delete()
    ArticleInstitucionMention.objects.filter(article_id__in=article_ids).delete()
    ArticleSentiment.objects.filter(article_id__in=article_ids).delete()
    ContentClassification.objects.filter(article_id__in=article_ids).delete()
    queryset.filter(id__in=article_ids).delete()

@admin.register(MediaOutlet)
class MediaOutletAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "is_active", "weight")
    search_fields = ("name", "slug")
    list_filter = ("type", "is_active")

@admin.register(MediaSource)
class MediaSourceAdmin(admin.ModelAdmin):
    list_display = ("media_outlet", "source_type", "is_active", "scan_interval_minutes", "last_fetched_at")
    search_fields = ("url",)
    list_filter = ("source_type", "is_active")

@admin.register(IngestRun)
class IngestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "trigger", "status", "time_window_start", "time_window_end", "started_at", "finished_at")
    list_filter = ("trigger", "status")

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("media_outlet", "published_at", "title")
    search_fields = ("title", "url")
    list_filter = ("media_outlet",)

    def delete_model(self, request, obj):
        with transaction.atomic():
            _purge_articles(Article.objects.filter(id=obj.id))

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            _purge_articles(queryset)

class StoryMentionInline(admin.TabularInline):
    model = StoryMention
    extra = 0
    autocomplete_fields = ("article", "media_outlet")

@admin.register(StoryCluster)
class StoryClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "confidence", "cohesion_score", "topic_label", "headline")
    search_fields = ("headline",)
    inlines = [StoryMentionInline]

@admin.register(StoryMention)
class StoryMentionAdmin(admin.ModelAdmin):
    list_display = ("cluster", "media_outlet", "article", "match_score")
    list_filter = ("media_outlet",)

@admin.register(Digest)
class DigestAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "created_at")
    search_fields = ("title",)
    date_hierarchy = "date"
    readonly_fields = ("json_content",)

@admin.register(ContentClassification)
class ContentClassificationAdmin(admin.ModelAdmin):
    list_display = ("article", "content_type", "confidence", "created_at")
    search_fields = ("article__title",)
    list_filter = ("content_type", "confidence")


@admin.register(ArticleSentiment)
class ArticleSentimentAdmin(admin.ModelAdmin):
    list_display = ("article", "sentiment", "confidence", "created_at")
    search_fields = ("article__title",)
    list_filter = ("sentiment", "confidence")

@admin.register(DigestClient)
class DigestClientAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(DigestClientConfig)
class DigestClientConfigAdmin(admin.ModelAdmin):
    list_display = ("client", "title", "top_n", "hours", "updated_at")
    search_fields = ("client__name", "title")
    filter_horizontal = ("personas", "instituciones")
