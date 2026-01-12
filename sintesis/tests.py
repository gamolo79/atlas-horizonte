from datetime import date, datetime
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from monitor.models import Article, Classification, Mention, Source
from redpolitica.models import Persona
from sintesis.models import SynthesisClient, SynthesisClientInterest
from sintesis.management.commands.run_sintesis import Command
from sintesis.run_builder import build_run, build_run_document


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
        build_run_document(run)
        run.refresh_from_db()
        self.assertTrue(run.pdf_file)

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

    @mock.patch("sintesis.views.call_command")
    def test_client_detail_run_manual_post_redirects(self, call_command_mock):
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
        call_command_mock.assert_called_once()
        _, kwargs = call_command_mock.call_args
        self.assertIsInstance(kwargs["date_from"], date)
        self.assertIsInstance(kwargs["date_to"], date)
