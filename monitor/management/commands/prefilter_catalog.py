from django.core.management.base import BaseCommand

from monitor.services import build_catalog, filter_catalog_for_text
from redpolitica.models import Institucion, Persona, Topic


class Command(BaseCommand):
    help = "Prefiltra el catálogo Atlas usando texto plano para revisar candidatos."

    def add_arguments(self, parser):
        parser.add_argument("--text", required=True, help="Texto de artículo o fragmento para prefiltrar.")
        parser.add_argument(
            "--show",
            type=int,
            default=5,
            help="Número de candidatos a mostrar por tipo.",
        )

    def handle(self, *args, **options):
        text = options["text"]
        show = options["show"]

        personas = Persona.objects.all()
        instituciones = Institucion.objects.all()
        temas = Topic.objects.all()
        catalog = build_catalog(personas, instituciones, temas)
        filtered = filter_catalog_for_text(text, catalog)

        for key, entries in filtered.items():
            self.stdout.write(f"{key}: {len(entries)} candidatos")
            for entry in entries[:show]:
                self.stdout.write(f"  - {entry.target_name}")
