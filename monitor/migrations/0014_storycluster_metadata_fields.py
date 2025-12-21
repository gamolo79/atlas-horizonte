from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0013_mention_entitylink_articleentity_and_alias_normalization"),
    ]

    operations = [
        migrations.AddField(
            model_name="storycluster",
            name="topic_label",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="storycluster",
            name="cohesion_score",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="storycluster",
            name="cluster_summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
