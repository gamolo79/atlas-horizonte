from django.test import TestCase
from django.utils import timezone

from monitor.models import Article, Classification, Mention, Source
from redpolitica.models import Persona
from sintesis.models import SynthesisClient, SynthesisClientInterest
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
