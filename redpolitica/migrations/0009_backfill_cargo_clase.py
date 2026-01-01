from django.db import migrations


def backfill_cargo_clase(apps, schema_editor):
    Cargo = apps.get_model("redpolitica", "Cargo")

    MAP = {
        # Legislativos
        "Diputada local": ("diputacion_local", "Diputación local"),
        "Diputado local": ("diputacion_local", "Diputación local"),
        "Diputada federal": ("diputacion_federal", "Diputación federal"),
        "Diputado federal": ("diputacion_federal", "Diputación federal"),
        "Senador": ("senaduria", "Senaduría"),
        "Senador de la República": ("senaduria", "Senaduría"),

        # Ejecutivos
        "Gobernador": ("gubernatura", "Gubernatura"),
        "Presidenta de México": ("presidencia_republica", "Presidencia de la República"),
        "Presidente de México": ("presidencia_republica", "Presidencia de la República"),
        "Presidenta Municipal": ("presidencia_municipal", "Presidencia municipal"),
        "Presidente Municipal": ("presidencia_municipal", "Presidencia municipal"),

        # Ayuntamientos
        "Regidor": ("regiduria", "Regiduría"),

        # Secretarías / gabinetes
        "Secretaria": ("secretaria", "Secretaría"),
        "Secretario": ("secretaria", "Secretaría"),
        "Secretario General": ("secretaria_general", "Secretaría General"),
        "Jefe de Gabinete": ("jefatura_gabinete", "Jefatura de Gabinete"),
        "Secretario Privado de Ricardo Anaya": ("secretaria_privada", "Secretaría privada"),

        # Direcciones / gestión
        "Director": ("direccion", "Dirección"),
        "Directora": ("direccion", "Dirección"),
        "Fiscal General": ("fiscalia_general", "Fiscalía General"),
        "Gerente General": ("gerencia_general", "Gerencia General"),
        "Titular": ("titularidad", "Titularidad"),
        "Coordinador": ("coordinacion", "Coordinación"),
        "Representante": ("representacion", "Representación"),

        # Candidaturas (proceso electoral)
        "Candidata a senadora de la República": ("candidatura_senaduria", "Candidatura al Senado"),
        "Candidato a senador de la República": ("candidatura_senaduria", "Candidatura al Senado"),
        "Candidato a Presidente Municipal": ("candidatura_presidencia_municipal", "Candidatura a Presidencia municipal"),

        # Privados / empresa
        "ADMINISTRADOR ÚNICO": ("administrador_unico", "Administrador único"),
        "Accionista": ("accionista", "Accionista"),
        "Apoderado": ("apoderado", "Apoderado"),
        "Apoderado y accionista": ("apoderado_accionista", "Apoderado y accionista"),

        # Genérico (luego lo afinamos si quieres)
        "Presidente": ("presidencia", "Presidencia"),
    }

    for c in Cargo.objects.all():
        if c.cargo_clase:  # no tocamos lo ya clasificado
            continue

        key = (c.nombre_cargo or "").strip()
        if key in MAP:
            clase, titulo = MAP[key]
            c.cargo_clase = clase
            c.cargo_titulo = titulo
            # cargo_codigo se llena en save() si está vacío
            c.save(update_fields=["cargo_clase", "cargo_titulo", "cargo_codigo"])


class Migration(migrations.Migration):

    dependencies = [
        ("redpolitica", "0008_militanciapartidista_cargo_cargo_clase_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_cargo_clase, migrations.RunPython.noop),
    ]
