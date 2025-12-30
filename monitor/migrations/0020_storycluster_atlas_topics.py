from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0019_article_atlas_topics"),
        ("redpolitica", "0005_topics_module"),
    ]

    operations = [
        migrations.AddField(
            model_name="storycluster",
            name="atlas_topics",
            field=models.ManyToManyField(blank=True, to="redpolitica.topic"),
        ),
    ]
