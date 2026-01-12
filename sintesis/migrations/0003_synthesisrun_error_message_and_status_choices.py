from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sintesis", "0002_synthesisclientinterest_interest_group_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="synthesisrun",
            name="error_message",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="synthesisrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "En cola"),
                    ("running", "En ejecución"),
                    ("completed", "Completado"),
                    ("failed", "Fallido"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
    ]
