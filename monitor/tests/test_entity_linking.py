from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from monitor.models import EntityLink, Mention, MediaOutlet
from redpolitica.models import Persona
from monitor.models import PersonaAlias, Article


class EntityLinkingTests(TestCase):
    def setUp(self):
        self.outlet = MediaOutlet.objects.create(
            name="Test Outlet",
            slug="test-outlet",
            type=MediaOutlet.MediaType.DIGITAL_NATIVE,
        )

    def test_person_alias_links(self):
        persona = Persona.objects.create(
            nombre_completo="Mauricio Kuri González",
            slug="mauricio-kuri-gonzalez",
        )
        PersonaAlias.objects.create(persona=persona, alias="Kuri")
        PersonaAlias.objects.create(persona=persona, alias="Mauricio Kuri")

        article = Article.objects.create(
            media_outlet=self.outlet,
            url="https://example.com/kuri",
            title="Kuri encabezó la reunión",
            body_text="El gobernador Kuri encabezó el evento.",
            published_at=timezone.now(),
        )

        call_command("link_entities", "--since", "1d")

        mention = Mention.objects.get(article=article)
        link = EntityLink.objects.get(mention=mention)
        self.assertEqual(link.status, EntityLink.Status.LINKED)
        self.assertGreaterEqual(link.confidence, 0.85)
        self.assertEqual(link.entity_id, persona.id)

    def test_ambiguity_stays_unlinked(self):
        Persona.objects.create(nombre_completo="Juan Garcia", slug="juan-garcia")
        Persona.objects.create(nombre_completo="Luis Garcia", slug="luis-garcia")

        article = Article.objects.create(
            media_outlet=self.outlet,
            url="https://example.com/garcia",
            title="Garcia dijo que no",
            body_text="Garcia negó los hechos.",
            published_at=timezone.now(),
        )

        call_command("link_entities", "--since", "1d")

        mention = Mention.objects.get(article=article)
        self.assertFalse(EntityLink.objects.filter(mention=mention).exists())

    def test_idempotent_linking(self):
        persona = Persona.objects.create(
            nombre_completo="Mauricio Kuri González",
            slug="mauricio-kuri-gonzalez-2",
        )
        PersonaAlias.objects.create(persona=persona, alias="Kuri")

        article = Article.objects.create(
            media_outlet=self.outlet,
            url="https://example.com/kuri-2",
            title="Kuri habló hoy",
            body_text="Kuri habló hoy con medios.",
            published_at=timezone.now(),
        )

        call_command("link_entities", "--since", "1d")
        call_command("link_entities", "--since", "1d")

        mention = Mention.objects.get(article=article)
        self.assertEqual(EntityLink.objects.filter(mention=mention).count(), 1)
