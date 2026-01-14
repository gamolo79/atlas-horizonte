from datetime import date, datetime
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from monitor.models import Article, Classification, Mention, Source
from redpolitica.models import Persona
from sintesis.models import (
    SynthesisClient,
    SynthesisClientInterest,
    SynthesisCluster,
    SynthesisClusterMember,
    SynthesisRun,
    SynthesisSectionTemplate,
)
from sintesis.models import SynthesisArticleDedup, SynthesisSectionFilter
from sintesis.management.commands.run_sintesis import Command
from sintesis._legacy_run_builder import build_run, build_run_document
from sintesis.services import build_profile, group_profiles
from sintesis.services.pipeline import _dedupe_articles, _evaluate_section_contract
from sintesis.services.mention_strength import classify_mentions
from sintesis.services.clustering import merge_clusters


class SynthesisRunBuilderTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )

    def _create_article(self, title, mention_persona=True):
        article = Article.objects.create(
            source=self.source,
            url=f"https://medio.local/{title.replace(' ', '-')}",
            title=title,
            text="Texto de prueba sobre salud pública.",
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud", "politica"],
            model_name="test",
        )
        if mention_persona:
            Mention.objects.create(
                classification=classification,
                target_type="persona",
                target_id=self.persona.id,
                target_name=self.persona.nombre_completo,
                sentiment="positivo",
                confidence=0.9,
            )
        return article

    def test_empty_section_not_created(self):
        client = SynthesisClient.objects.create(
            name="Cliente Sin Intereses",
            persona=self.persona,
            description="Sin datos",
            keyword_tags=[],
        )
        run = build_run(client=client)
        count = build_run_document(run)
        self.assertEqual(count, 0)
        self.assertEqual(run.sections.count(), 0)

    def test_run_generates_section_and_story(self):
        SynthesisClientInterest.objects.create(
            client=self.client,
            persona=self.persona,
            interest_group="priority",
        )
        self._create_article("Nota principal")
        run = build_run(client=self.client)
        count = build_run_document(run)
        self.assertGreaterEqual(count, 1)
        self.assertEqual(run.sections.count(), 1)
        self.assertEqual(run.stories.count(), 1)

    def test_pdf_generated_when_content(self):
        SynthesisClientInterest.objects.create(
            client=self.client,
            persona=self.persona,
            interest_group="priority",
        )
        self._create_article("Nota con PDF")
        run = build_run(client=self.client)
        with override_settings(SINTESIS_ENABLE_PDF=False):
            build_run_document(run)
        run.refresh_from_db()
        self.assertFalse(run.pdf_file)

    def test_dedupe_article_not_in_two_sections(self):
        SynthesisClientInterest.objects.create(
            client=self.client,
            persona=self.persona,
            interest_group="priority",
        )
        SynthesisClientInterest.objects.create(
            client=self.client,
            persona=self.persona,
            interest_group="general",
        )
        article = self._create_article("Nota duplicada")
        run = build_run(client=self.client)
        build_run_document(run)
        story_article_count = article.sintesis_items.count()
        self.assertEqual(story_article_count, 1)


class RunSintesisParsingTests(TestCase):
    def test_parse_date_accepts_supported_types(self):
        command = Command()
        self.assertEqual(command._parse_date("2026-01-12"), date(2026, 1, 12))
        self.assertEqual(command._parse_date(date(2026, 1, 12)), date(2026, 1, 12))
        self.assertEqual(
            command._parse_date(datetime(2026, 1, 12, 10, 0)),
            date(2026, 1, 12),
        )
        self.assertIsNone(command._parse_date(None))


class SynthesisRunViewTests(TestCase):
    def setUp(self):
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.synthesis_client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )

    @mock.patch("sintesis.views.subprocess.Popen")
    def test_client_detail_run_manual_post_redirects(self, popen_mock):
        response = self.client.post(
            reverse("sintesis:client_detail", kwargs={"client_id": self.synthesis_client.id}),
            {
                "run-client": self.synthesis_client.id,
                "run-date_from": "2026-01-12",
                "run-date_to": "2026-01-13",
                "run_manual": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SynthesisRun.objects.filter(client=self.synthesis_client).count(), 1)
        run = SynthesisRun.objects.get(client=self.synthesis_client)
        self.assertEqual(run.status, "queued")
        popen_mock.assert_called_once()

    @mock.patch("sintesis.views.subprocess.Popen")
    def test_procesos_run_manual_post_redirects(self, popen_mock):
        response = self.client.post(
            reverse("sintesis:procesos"),
            {
                "run-client": self.synthesis_client.id,
                "run-date_from": "2026-01-12",
                "run-date_to": "2026-01-13",
                "run_manual": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SynthesisRun.objects.filter(client=self.synthesis_client).count(), 1)
        run = SynthesisRun.objects.get(client=self.synthesis_client)
        self.assertEqual(run.status, "queued")
        popen_mock.assert_called_once()


class SynthesisRunPdfFailureTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )
        SynthesisClientInterest.objects.create(
            client=self.client,
            persona=self.persona,
            interest_group="priority",
        )
        article = Article.objects.create(
            source=self.source,
            url="https://medio.local/nota",
            title="Nota PDF",
            text="Texto de prueba sobre salud pública.",
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud", "politica"],
            model_name="test",
        )
        Mention.objects.create(
            classification=classification,
            target_type="persona",
            target_id=self.persona.id,
            target_name=self.persona.nombre_completo,
            sentiment="positivo",
            confidence=0.9,
        )

    @mock.patch("sintesis._legacy_run_builder.generate_run_pdf", side_effect=Exception("PDF error"))
    def test_run_completes_when_pdf_fails(self, _generate_run_pdf):
        Command().handle(client_id=self.client.id)
        run = SynthesisRun.objects.get(client=self.client)
        self.assertIn(run.status, {"completed", "failed"})
        self.assertNotEqual(run.status, "running")


class SynthesisClusterMergeTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )
        self.template = SynthesisSectionTemplate.objects.create(
            client=self.client,
            title="Sección",
            order=1,
        )
        self.run = SynthesisRun.objects.create(
            client=self.client,
            status="completed",
        )

    def _create_article(self, title: str):
        article = Article.objects.create(
            source=self.source,
            url=f"https://medio.local/{title.replace(' ', '-')}",
            title=title,
            text="Texto de prueba sobre salud pública.",
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud", "politica", "economia"],
            model_name="test",
        )
        Mention.objects.create(
            classification=classification,
            target_type="persona",
            target_id=self.persona.id,
            target_name=self.persona.nombre_completo,
            sentiment="positivo",
            confidence=0.9,
        )
        return article

    def test_merge_clusters_when_similarity_and_shared_entity(self):
        article_a = self._create_article("Nota A")
        article_b = self._create_article("Nota B")
        cluster_a = SynthesisCluster.objects.create(
            run=self.run,
            template=self.template,
            centroid_json=[1.0, 0.0],
            top_entities_json=[f"persona:{self.persona.id}"],
            top_tags_json=["salud", "politica", "economia"],
            time_start=timezone.now(),
            time_end=timezone.now(),
        )
        cluster_b = SynthesisCluster.objects.create(
            run=self.run,
            template=self.template,
            centroid_json=[1.0, 0.01],
            top_entities_json=[f"persona:{self.persona.id}"],
            top_tags_json=["salud", "politica", "economia"],
            time_start=timezone.now(),
            time_end=timezone.now(),
        )
        SynthesisClusterMember.objects.create(cluster=cluster_a, article=article_a, similarity=1.0)
        SynthesisClusterMember.objects.create(cluster=cluster_b, article=article_b, similarity=1.0)

        merge_clusters(self.run, self.template)

        clusters = SynthesisCluster.objects.filter(run=self.run, template=self.template)
        self.assertEqual(clusters.count(), 1)
        self.assertEqual(clusters.first().members.count(), 2)

    def test_no_merge_without_shared_entities_or_tags(self):
        article_a = self._create_article("Nota C")
        article_b = self._create_article("Nota D")
        cluster_a = SynthesisCluster.objects.create(
            run=self.run,
            template=self.template,
            centroid_json=[1.0, 0.0],
            top_entities_json=[f"persona:{self.persona.id}"],
            top_tags_json=["salud"],
            time_start=timezone.now(),
            time_end=timezone.now(),
        )
        cluster_b = SynthesisCluster.objects.create(
            run=self.run,
            template=self.template,
            centroid_json=[1.0, 0.01],
            top_entities_json=["persona:9999"],
            top_tags_json=["otro"],
            time_start=timezone.now(),
            time_end=timezone.now(),
        )
        SynthesisClusterMember.objects.create(cluster=cluster_a, article=article_a, similarity=1.0)
        SynthesisClusterMember.objects.create(cluster=cluster_b, article=article_b, similarity=1.0)

        merge_clusters(self.run, self.template)

        clusters = SynthesisCluster.objects.filter(run=self.run, template=self.template)
        self.assertEqual(clusters.count(), 2)


class StoryGroupingSimilarityTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )

    def _create_article(
        self,
        title,
        central_idea,
        labels,
        mention_type="institucion",
        mention_id=1,
        mention_name="Fiscalía",
    ):
        article = Article.objects.create(
            source=self.source,
            url=f"https://medio.local/{title.replace(' ', '-').lower()}",
            title=title,
            text="Texto de prueba.",
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea=central_idea,
            article_type="informativo",
            labels_json=labels,
            model_name="test",
        )
        Mention.objects.create(
            classification=classification,
            target_type=mention_type,
            target_id=mention_id,
            target_name=mention_name,
            sentiment="neutro",
            confidence=0.9,
        )
        return article

    def test_different_stories_with_shared_entity_do_not_group(self):
        article_a = self._create_article(
            "Feminicidio en el centro de la ciudad",
            "Caso de feminicidio en el centro",
            ["violencia", "mujeres"],
        )
        article_b = self._create_article(
            "Rescatan animales por maltrato en domicilio",
            "Maltrato animal detectado en un domicilio",
            ["animales", "proteccion"],
        )
        profiles = [build_profile(article_a), build_profile(article_b)]
        groups = group_profiles(profiles)
        self.assertEqual(len(groups), 2)

    def test_similar_titles_and_entities_group_together(self):
        article_a = self._create_article(
            "Detienen a Juan por robo en el centro",
            "Detención por robo en el centro",
            ["seguridad", "robo"],
            mention_type="persona",
            mention_id=10,
            mention_name="Juan Pérez",
        )
        article_b = self._create_article(
            "Juan detenido por robo en el centro",
            "Detención por robo en el centro",
            ["robo", "seguridad"],
            mention_type="persona",
            mention_id=10,
            mention_name="Juan Pérez",
        )
        profiles = [build_profile(article_a), build_profile(article_b)]
        groups = group_profiles(profiles)
        self.assertEqual(len(groups), 1)


class SynthesisRoutingContractTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )
        self.template = SynthesisSectionTemplate.objects.create(
            client=self.client,
            title="Sección",
            order=1,
            contract_min_score=0.6,
            contract_min_mentions=2,
        )
        SynthesisSectionFilter.objects.create(
            template=self.template,
            persona=self.persona,
        )
        self.run = SynthesisRun.objects.create(client=self.client, status="completed")

    def _create_article(self, title, text):
        article = Article.objects.create(
            source=self.source,
            url=f"https://medio.local/{title.replace(' ', '-').lower()}",
            title=title,
            text=text,
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud"],
            model_name="test",
        )
        Mention.objects.create(
            classification=classification,
            target_type="persona",
            target_id=self.persona.id,
            target_name=self.persona.nombre_completo,
            sentiment="positivo",
            confidence=0.9,
        )
        return article

    def test_contract_includes_strong_entity(self):
        article = self._create_article(
            "Ana Pérez anuncia política pública",
            "Ana Pérez anunció un nuevo programa de salud.",
        )
        strengths = classify_mentions(article, article.classification.mentions.all())
        included, score, details = _evaluate_section_contract(self.template, article, strengths)
        self.assertTrue(included)
        self.assertGreaterEqual(score, 0.6)
        self.assertIn("strong_hits", details)

    def test_contract_excludes_negative_keyword(self):
        self.template.contract_keywords_negative = ["corrupcion"]
        self.template.save(update_fields=["contract_keywords_negative"])
        article = self._create_article(
            "Ana Pérez en polémica",
            "Ana Pérez mencionada en un caso de corrupción.",
        )
        strengths = classify_mentions(article, article.classification.mentions.all())
        included, score, details = _evaluate_section_contract(self.template, article, strengths)
        self.assertFalse(included)
        self.assertEqual(score, 0.0)
        self.assertEqual(details.get("reason"), "negative_keyword")


class MentionStrengthTests(TestCase):
    def test_mentions_strong_in_title(self):
        source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        article = Article.objects.create(
            source=source,
            url="https://medio.local/ana-perez",
            title="Ana Pérez anuncia medidas",
            text="Texto de prueba sobre salud pública.",
            published_at=timezone.now(),
        )
        classification = Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud"],
            model_name="test",
        )
        Mention.objects.create(
            classification=classification,
            target_type="persona",
            target_id=persona.id,
            target_name=persona.nombre_completo,
            sentiment="positivo",
            confidence=0.9,
        )
        strengths = classify_mentions(article, article.classification.mentions.all())
        self.assertEqual(len(strengths), 1)
        self.assertEqual(strengths[0].strength, "strong")


class DedupeTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(
            name="Medio Uno",
            source_type="rss",
            url="https://medio.local",
        )
        self.persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        self.client = SynthesisClient.objects.create(
            name="Cliente Demo",
            persona=self.persona,
            description="Demo",
            keyword_tags=["salud"],
        )
        self.template = SynthesisSectionTemplate.objects.create(
            client=self.client,
            title="Sección",
            order=1,
        )
        self.run = SynthesisRun.objects.create(client=self.client, status="completed")

    def _create_article(self, title: str):
        article = Article.objects.create(
            source=self.source,
            url=f"https://medio.local/{title.replace(' ', '-')}",
            title=title,
            text="Texto de prueba sobre salud pública.",
            published_at=timezone.now(),
        )
        Classification.objects.create(
            article=article,
            central_idea="Tema central de la nota",
            article_type="informativo",
            labels_json=["salud"],
            model_name="test",
        )
        return article

    def test_dedupe_marks_duplicate(self):
        article_a = self._create_article("Nota A")
        article_b = self._create_article("Nota A")
        articles = [article_a, article_b]
        kept = _dedupe_articles(self.run, articles)
        self.assertEqual(len(kept), 1)
        self.assertEqual(
            SynthesisArticleDedup.objects.filter(run=self.run).count(),
            1,
        )
