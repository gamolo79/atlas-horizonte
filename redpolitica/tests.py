from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import (
    Cargo,
    Institucion,
    InstitutionTopic,
    Persona,
    PersonTopicManual,
    Topic,
)


class TopicModuleTests(TestCase):
    def test_topic_slug_autogenerates(self):
        topic = Topic.objects.create(name="Transparencia y Datos")
        self.assertTrue(topic.slug)
        self.assertEqual(topic.slug, "transparencia-y-datos")

    def test_institution_topic_unique_constraint(self):
        institucion = Institucion.objects.create(nombre="Gobierno", slug="gobierno")
        topic = Topic.objects.create(name="Gobernanza")
        InstitutionTopic.objects.create(
            institution=institucion,
            topic=topic,
            role="función principal",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InstitutionTopic.objects.create(
                    institution=institucion,
                    topic=topic,
                    role="función principal",
                )

    def test_person_topic_manual_unique_constraint(self):
        persona = Persona.objects.create(nombre_completo="Ana Pérez", slug="ana-perez")
        topic = Topic.objects.create(name="Innovación")
        PersonTopicManual.objects.create(person=persona, topic=topic, role="vocera")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PersonTopicManual.objects.create(
                    person=persona,
                    topic=topic,
                    role="vocera",
                )

    def test_topic_graph_json_includes_nodes_and_edges(self):
        institucion = Institucion.objects.create(nombre="Secretaría", slug="secretaria")
        persona = Persona.objects.create(nombre_completo="Carlos López", slug="carlos-lopez")
        topic = Topic.objects.create(name="Movilidad")
        InstitutionTopic.objects.create(
            institution=institucion,
            topic=topic,
            role="programa",
        )
        PersonTopicManual.objects.create(
            person=persona,
            topic=topic,
            role="promotor",
        )
        Cargo.objects.create(
            persona=persona,
            institucion=institucion,
            nombre_cargo="Director",
        )

        response = self.client.get(
            reverse("atlas-topic-graph-json", kwargs={"slug": topic.slug})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        node_ids = {node["id"] for node in data["nodes"]}
        edge_types = {edge["type"] for edge in data["edges"]}

        self.assertIn(f"topic:{topic.id}", node_ids)
        self.assertIn(f"inst:{institucion.id}", node_ids)
        self.assertIn(f"person:{persona.id}", node_ids)
        self.assertIn("institution_topic", edge_types)
        self.assertIn("person_topic_manual", edge_types)
