from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q
from django.utils import timezone

from atlas_core.text_utils import normalize_name


def populate_alias_normalized(apps, schema_editor):
    PersonaAlias = apps.get_model("monitor", "PersonaAlias")
    InstitucionAlias = apps.get_model("monitor", "InstitucionAlias")
    for alias in PersonaAlias.objects.all():
        alias.alias_normalizado = normalize_name(alias.alias)
        alias.save(update_fields=["alias_normalizado"])
    for alias in InstitucionAlias.objects.all():
        alias.alias_normalizado = normalize_name(alias.alias)
        alias.save(update_fields=["alias_normalizado"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0012_mention_sentiment_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="personaalias",
            name="alias_normalizado",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="institucionalias",
            name="alias_normalizado",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.RunPython(populate_alias_normalized, reverse_code=noop_reverse),
        migrations.CreateModel(
            name="Mention",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("surface", models.TextField()),
                ("normalized_surface", models.TextField(db_index=True)),
                (
                    "entity_kind",
                    models.CharField(
                        choices=[
                            ("PERSON", "Persona"),
                            ("ORG", "Organización"),
                            ("ROLE", "Rol"),
                            ("OTHER", "Otro"),
                        ],
                        max_length=10,
                    ),
                ),
                ("context_window", models.TextField(blank=True)),
                ("span_start", models.IntegerField(blank=True, null=True)),
                ("span_end", models.IntegerField(blank=True, null=True)),
                ("method", models.CharField(blank=True, max_length=60)),
                ("created_at", models.DateTimeField(default=timezone.now)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mentions",
                        to="monitor.article",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["article", "entity_kind"], name="monitor_men_article_6f6e5d_idx"),
                    models.Index(fields=["normalized_surface"], name="monitor_men_normali_4ec687_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["article", "entity_kind", "span_start", "span_end", "normalized_surface"],
                        name="uniq_mention_span",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EntityLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "entity_type",
                    models.CharField(
                        choices=[("PERSON", "Persona"), ("INSTITUTION", "Institución")],
                        max_length=20,
                    ),
                ),
                ("entity_id", models.IntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("linked", "Linked"), ("proposed", "Proposed"), ("rejected", "Rejected")],
                        default="proposed",
                        max_length=20,
                    ),
                ),
                ("confidence", models.FloatField(default=0.0)),
                ("reasons", models.JSONField(blank=True, default=list)),
                ("resolver_version", models.CharField(blank=True, default="linker_v1", max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mention",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entity_links",
                        to="monitor.mention",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["entity_type", "entity_id"], name="monitor_ent_entity__5f06d0_idx"),
                    models.Index(fields=["status"], name="monitor_ent_status_3791e3_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=Q(("status", "linked")),
                        fields=("mention",),
                        name="uniq_linked_mention",
                    ),
                    models.UniqueConstraint(
                        fields=("mention", "entity_type", "entity_id", "status"),
                        name="uniq_link_per_entity_status",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ArticleEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("PERSON", "Persona"), ("INSTITUTION", "Institución")], max_length=20)),
                ("entity_id", models.IntegerField()),
                ("max_confidence", models.FloatField(default=0.0)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_entities",
                        to="monitor.article",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("article", "entity_type", "entity_id"),
                        name="uniq_article_entity",
                    ),
                ],
            },
        ),
    ]
