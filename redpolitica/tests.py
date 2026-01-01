from django.db import IntegrityError, transaction
from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import (
    Cargo,
    Institucion,
    InstitutionTopic,
    Persona,
    PeriodoAdministrativo,
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


class GrafoEndpointsTests(TestCase):
    def test_institucion_grafo_unifica_persona_y_periodos(self):
        institucion = Institucion.objects.create(
            nombre="Congreso local",
            slug="congreso-local",
        )
        persona = Persona.objects.create(
            nombre_completo="Guillermo Vega",
            slug="guillermo-vega",
        )
        periodos = [
            PeriodoAdministrativo.objects.create(
                tipo="LEGISLATURA",
                nivel="ESTATAL",
                nombre="Legislatura I",
                fecha_inicio=date(2010, 1, 1),
                fecha_fin=date(2013, 12, 31),
            ),
            PeriodoAdministrativo.objects.create(
                tipo="LEGISLATURA",
                nivel="ESTATAL",
                nombre="Legislatura II",
                fecha_inicio=date(2014, 1, 1),
                fecha_fin=date(2017, 12, 31),
            ),
            PeriodoAdministrativo.objects.create(
                tipo="LEGISLATURA",
                nivel="ESTATAL",
                nombre="Legislatura III",
                fecha_inicio=date(2018, 1, 1),
                fecha_fin=date(2021, 12, 31),
            ),
        ]
        for idx, periodo in enumerate(periodos, start=1):
            Cargo.objects.create(
                persona=persona,
                institucion=institucion,
                periodo=periodo,
                nombre_cargo=f"Diputado {idx}",
            )

        response = self.client.get(
            reverse("institucion-grafo", kwargs={"slug": institucion.slug})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        personas = data.get("personas", [])
        cargos = data.get("cargos", [])

        self.assertEqual(len([p for p in personas if p["id"] == persona.id]), 1)
        self.assertEqual(len(cargos), 3)
        self.assertEqual(
            len({c["periodo_id"] for c in cargos}),
            3,
        )

        persona_payload = next(p for p in personas if p["id"] == persona.id)
        periodos_en_inst = persona_payload.get("periodos_en_institucion", [])
        self.assertEqual(len(periodos_en_inst), 3)
