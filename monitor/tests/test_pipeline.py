from django.test import TestCase
from django.utils import timezone

from monitor.models import (
    ActorLink,
    Article,
    ClassificationRun,
    Correction,
    MetricAggregate,
    Source,
    Story,
    StoryArticle,
    TopicLink,
    TrainingExample,
)
from monitor.pipeline import (
    aggregate_metrics,
    classify_articles,
    cluster_stories,
    ingest_sources,
    normalize_articles,
)


class MonitorPipelineTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Test",
            outlet="Outlet",
            source_type=Source.SourceType.RSS,
            url="https://example.com/rss",
        )

    def test_ingest_dedupe_hash(self):
        articles = ingest_sources(limit=1)
        self.assertEqual(len(articles), 1)
        article = articles[0]
        duplicate_hash = Article.compute_hash(article.url, article.canonical_url, article.body)
        self.assertEqual(article.hash_dedupe, duplicate_hash)

    def test_normalize_creates_version(self):
        article = Article.objects.create(
            source=self.source,
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Titulo",
            body="<p>texto</p>",
            published_at=timezone.now(),
            fetched_at=timezone.now(),
            outlet="Outlet",
            hash_dedupe=Article.compute_hash("https://example.com/a", "https://example.com/a", "texto"),
        )
        normalize_articles([article])
        article.refresh_from_db()
        self.assertEqual(article.pipeline_status, Article.PipelineStatus.NORMALIZED)
        self.assertEqual(article.versions.count(), 1)

    def test_classification_json_payload(self):
        article = Article.objects.create(
            source=self.source,
            url="https://example.com/b",
            canonical_url="https://example.com/b",
            title="Titulo",
            body="texto",
            published_at=timezone.now(),
            fetched_at=timezone.now(),
            outlet="Outlet",
            hash_dedupe=Article.compute_hash("https://example.com/b", "https://example.com/b", "texto"),
        )
        classify_articles([article])
        run = ClassificationRun.objects.get(article=article)
        payload = run.extraction.raw_payload
        self.assertIn("content_type", payload)
        self.assertIsInstance(payload, dict)

    def test_clustering_stable(self):
        article_one = Article.objects.create(
            source=self.source,
            url="https://example.com/c",
            canonical_url="https://example.com/c",
            title="Nota 1",
            body="texto",
            published_at=timezone.now(),
            fetched_at=timezone.now(),
            outlet="Outlet",
            hash_dedupe=Article.compute_hash("https://example.com/c", "https://example.com/c", "texto"),
        )
        article_two = Article.objects.create(
            source=self.source,
            url="https://example.com/d",
            canonical_url="https://example.com/d",
            title="Nota 2",
            body="texto",
            published_at=timezone.now(),
            fetched_at=timezone.now(),
            outlet="Outlet",
            hash_dedupe=Article.compute_hash("https://example.com/d", "https://example.com/d", "texto"),
        )
        TopicLink.objects.create(article=article_one, atlas_topic_id="GENERAL", confidence=0.5)
        TopicLink.objects.create(article=article_two, atlas_topic_id="GENERAL", confidence=0.5)
        cluster_stories(hours=1)
        self.assertEqual(Story.objects.count(), 1)
        self.assertEqual(StoryArticle.objects.count(), 2)

    def test_aggregate_metrics(self):
        article = Article.objects.create(
            source=self.source,
            url="https://example.com/e",
            canonical_url="https://example.com/e",
            title="Nota",
            body="texto",
            published_at=timezone.now(),
            fetched_at=timezone.now(),
            outlet="Outlet",
            hash_dedupe=Article.compute_hash("https://example.com/e", "https://example.com/e", "texto"),
        )
        ActorLink.objects.create(
            article=article,
            atlas_entity_id="123",
            atlas_entity_type=ActorLink.AtlasEntityType.PERSONA,
            sentiment=ActorLink.Sentiment.POSITIVO,
            sentiment_confidence=0.7,
        )
        aggregate_metrics()
        self.assertTrue(MetricAggregate.objects.filter(atlas_id="123").exists())

    def test_corrections_create_training_example(self):
        correction = Correction.objects.create(
            scope=Correction.Scope.ARTICLE,
            target_id=1,
            field_name="scope",
            old_value="federal",
            new_value="estatal",
            explanation="ajuste editorial",
        )
        example = TrainingExample.objects.get(correction=correction)
        self.assertEqual(example.explanation, "ajuste editorial")
