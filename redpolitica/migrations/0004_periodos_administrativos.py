from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("redpolitica", "0003_persona_institucion_normalized_names"),
    ]

    operations = [
        migrations.CreateModel(
            name="PeriodoAdministrativo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo", models.CharField(choices=[("SEXENIO", "Sexenio"), ("TRIENIO", "Trienio"), ("LEGISLATURA", "Legislatura"), ("PROCESO_ELECTORAL", "Proceso electoral")], max_length=20)),
                ("nivel", models.CharField(choices=[("ESTATAL", "Estatal"), ("MUNICIPAL", "Municipal"), ("LEGISLATIVO", "Legislativo")], max_length=20)),
                ("nombre", models.CharField(max_length=100, unique=True)),
                ("fecha_inicio", models.DateField()),
                ("fecha_fin", models.DateField()),
                (
                    "institucion_raiz",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="periodos", to="redpolitica.institucion"),
                ),
            ],
            options={
                "ordering": ["fecha_inicio"],
            },
        ),
        migrations.CreateModel(
            name="Legislatura",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=100)),
                ("numero", models.PositiveIntegerField(blank=True, null=True)),
                ("notas", models.TextField(blank=True)),
                (
                    "periodo",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legislaturas", to="redpolitica.periodoadministrativo"),
                ),
            ],
            options={
                "ordering": ["periodo__fecha_inicio", "nombre"],
                "unique_together": {("periodo", "nombre")},
            },
        ),
        migrations.RemoveField(
            model_name="institucion",
            name="fecha_fin",
        ),
        migrations.RemoveField(
            model_name="institucion",
            name="fecha_inicio",
        ),
        migrations.AddField(
            model_name="cargo",
            name="periodo",
            field=models.ForeignKey(blank=True, help_text="Periodo administrativo asociado (sexenio, trienio, legislatura, etc.).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cargos", to="redpolitica.periodoadministrativo"),
        ),
    ]
