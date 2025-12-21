from django.db import migrations, models

from atlas_core.text_utils import normalize_name


def populate_normalized_names(apps, schema_editor):
    Persona = apps.get_model("redpolitica", "Persona")
    Institucion = apps.get_model("redpolitica", "Institucion")
    for persona in Persona.objects.all():
        persona.nombre_normalizado = normalize_name(persona.nombre_completo)
        persona.save(update_fields=["nombre_normalizado"])
    for institucion in Institucion.objects.all():
        institucion.nombre_normalizado = normalize_name(institucion.nombre)
        institucion.save(update_fields=["nombre_normalizado"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("redpolitica", "0002_alter_relacion_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="persona",
            name="nombre_normalizado",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="institucion",
            name="nombre_normalizado",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.RunPython(populate_normalized_names, reverse_code=noop_reverse),
    ]
