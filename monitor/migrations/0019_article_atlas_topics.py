from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("redpolitica", "0005_topics_module"),
        ("monitor", "0018_monitortopicmapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="atlas_topics",
            field=models.ManyToManyField(blank=True, to="redpolitica.topic"),
        ),
    ]
