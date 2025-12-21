from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitor", "0010_digestclient_digestclientconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="guid",
            field=models.CharField(blank=True, db_index=True, max_length=500),
        ),
    ]
