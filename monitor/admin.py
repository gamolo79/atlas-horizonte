from django.contrib import admin
from .models import MediaOutlet, MediaSource, IngestRun, Article, StoryCluster, StoryMention, Digest, ContentClassification, ArticleSentiment, DigestClient, DigestClientConfig

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

class StoryMentionInline(admin.TabularInline):
    model = StoryMention
    extra = 0
    autocomplete_fields = ("article", "media_outlet")

@admin.register(StoryCluster)
class StoryClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "confidence", "headline")
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
