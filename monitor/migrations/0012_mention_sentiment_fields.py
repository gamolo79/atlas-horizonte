from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0011_article_guid"),
    ]

    operations = [
        migrations.AddField(
            model_name="articlepersonamention",
            name="sentiment",
            field=models.CharField(
                blank=True,
                choices=[
                    ("positivo", "Positivo"),
                    ("neutro", "Neutro"),
                    ("negativo", "Negativo"),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="articlepersonamention",
            name="sentiment_confidence",
            field=models.CharField(
                blank=True,
                choices=[("alta", "Alta"), ("media", "Media"), ("baja", "Baja")],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="articlepersonamention",
            name="sentiment_justification",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="articlepersonamention",
            name="sentiment_model",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
        migrations.AddField(
            model_name="articleinstitucionmention",
            name="sentiment",
            field=models.CharField(
                blank=True,
                choices=[
                    ("positivo", "Positivo"),
                    ("neutro", "Neutro"),
                    ("negativo", "Negativo"),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="articleinstitucionmention",
            name="sentiment_confidence",
            field=models.CharField(
                blank=True,
                choices=[("alta", "Alta"), ("media", "Media"), ("baja", "Baja")],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="articleinstitucionmention",
            name="sentiment_justification",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="articleinstitucionmention",
            name="sentiment_model",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
    ]
