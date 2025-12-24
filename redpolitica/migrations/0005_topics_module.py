from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("redpolitica", "0004_periodos_administrativos"),
    ]

    operations = [
        migrations.CreateModel(
            name="Topic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
                ("slug", models.SlugField(blank=True, max_length=150, unique=True)),
                ("description", models.TextField(blank=True, null=True)),
                ("topic_kind", models.CharField(choices=[("public_function", "Función Pública"), ("private_objective", "Objetivo Privado"), ("cross_cutting", "Transversal")], default="cross_cutting", max_length=40)),
                ("status", models.CharField(choices=[("active", "Activo"), ("archived", "Archivado")], default="active", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="redpolitica.topic"),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="InstitutionTopic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(max_length=100)),
                ("note", models.TextField(blank=True, null=True)),
                ("valid_from", models.DateField(blank=True, null=True)),
                ("valid_to", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "institution",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="temas_relacionados", to="redpolitica.institucion"),
                ),
                (
                    "topic",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="institution_links", to="redpolitica.topic"),
                ),
            ],
            options={
                "ordering": ["topic", "institution", "role"],
            },
        ),
        migrations.CreateModel(
            name="PersonTopicManual",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(max_length=100)),
                ("note", models.TextField(blank=True, null=True)),
                ("source_url", models.URLField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "person",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="temas_manual", to="redpolitica.persona"),
                ),
                (
                    "topic",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="person_links", to="redpolitica.topic"),
                ),
            ],
            options={
                "ordering": ["topic", "person", "role"],
            },
        ),
        migrations.AddIndex(
            model_name="topic",
            index=models.Index(fields=["slug"], name="redpolitica_slug_6e2845_idx"),
        ),
        migrations.AddIndex(
            model_name="topic",
            index=models.Index(fields=["name"], name="redpolitica_name_8f20b4_idx"),
        ),
        migrations.AddIndex(
            model_name="topic",
            index=models.Index(fields=["topic_kind", "status"], name="redpolitica_topic_k_0e129b_idx"),
        ),
        migrations.AddConstraint(
            model_name="institutiontopic",
            constraint=models.UniqueConstraint(fields=("institution", "topic", "role"), name="uniq_institution_topic_role"),
        ),
        migrations.AddConstraint(
            model_name="persontopicmanual",
            constraint=models.UniqueConstraint(fields=("person", "topic", "role"), name="uniq_person_topic_role"),
        ),
    ]
