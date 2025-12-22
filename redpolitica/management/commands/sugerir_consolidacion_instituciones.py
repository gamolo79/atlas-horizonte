import re

from django.core.management.base import BaseCommand

from atlas_core.text_utils import normalize_name
from redpolitica.models import Institucion


class Command(BaseCommand):
    help = (
        "Sugiere consolidaciones para instituciones con años en el nombre "
        "(regex \\d{4}). No modifica datos, sólo imprime recomendaciones."
    )

    def handle(self, *args, **options):
        patron_anios = re.compile(r"\d{4}")
        instituciones = list(Institucion.objects.all())
        normalizadas = {}

        for inst in instituciones:
            clave = normalize_name(inst.nombre)
            normalizadas.setdefault(clave, []).append(inst)

        sospechosas = []
        for inst in instituciones:
            if patron_anios.search(inst.nombre):
                sospechosas.append(inst)

        if not sospechosas:
            self.stdout.write("No se encontraron instituciones con años en el nombre.")
            return

        self.stdout.write("Instituciones con años en el nombre y sugerencias de consolidación:\n")
        for inst in sospechosas:
            nombre_base = re.sub(r"\d{4}(\s*[–-]\s*\d{4})?", "", inst.nombre).strip()
            nombre_base = nombre_base.strip("()–- ").strip()
            clave_base = normalize_name(nombre_base) if nombre_base else None
            candidatos = normalizadas.get(clave_base, []) if clave_base else []
            candidatos = [c for c in candidatos if c.id != inst.id]

            self.stdout.write(f"- {inst.nombre} (id={inst.id})")
            if nombre_base:
                self.stdout.write(f"  Nombre base sugerido: '{nombre_base}'")
            if candidatos:
                sugeridos = ", ".join(f"{c.nombre} (id={c.id})" for c in candidatos[:5])
                self.stdout.write(f"  Coincidencias posibles: {sugeridos}")
            else:
                self.stdout.write("  Coincidencias posibles: (ninguna)")
            if inst.padre:
                self.stdout.write(
                    f"  Institución padre actual: {inst.padre.nombre} (id={inst.padre.id})"
                )
            self.stdout.write("")
