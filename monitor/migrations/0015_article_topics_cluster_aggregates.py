from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0014_storycluster_metadata_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="topics",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="article",
            name="topics_justification",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="article",
            name="topics_model",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
        migrations.AddField(
            model_name="storycluster",
            name="entity_summary",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="storycluster",
            name="sentiment_summary",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="storycluster",
            name="topic_summary",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
