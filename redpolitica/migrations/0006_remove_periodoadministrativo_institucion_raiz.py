from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("redpolitica", "0005_alter_legislatura_periodo_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="periodoadministrativo",
            name="institucion_raiz",
        ),
    ]
