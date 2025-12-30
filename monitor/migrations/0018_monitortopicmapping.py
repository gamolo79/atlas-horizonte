from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("redpolitica", "0005_topics_module"),
        ("monitor", "0017_article_training_reviewed"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitorTopicMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("monitor_label", models.CharField(max_length=200, unique=True)),
                ("method", models.CharField(blank=True, max_length=60)),
                (
                    "atlas_topic",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="monitor_mappings", to="redpolitica.topic"),
                ),
            ],
            options={
                "ordering": ["monitor_label"],
            },
        ),
    ]
