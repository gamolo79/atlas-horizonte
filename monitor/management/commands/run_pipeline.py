from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Corre ingesta y clasificación en secuencia."

    def add_arguments(self, parser):
        parser.add_argument("--date-from", dest="date_from", help="Fecha inicio YYYY-MM-DD")
        parser.add_argument("--date-to", dest="date_to", help="Fecha fin YYYY-MM-DD")
        parser.add_argument("--limit-sources", type=int, default=10)
        parser.add_argument("--limit-articles", type=int, default=10)
        parser.add_argument("--limit-classify", type=int, default=50)

    def handle(self, *args, **options):
        date_from = options.get("date_from")
        date_to = options.get("date_to")
        limit_sources = options["limit_sources"]
        limit_articles = options["limit_articles"]
        limit_classify = options["limit_classify"]

        self.stdout.write("Ejecutando fetch_sources...")
        call_command("fetch_sources", limit=limit_articles, limit_sources=limit_sources)

        self.stdout.write("Ejecutando classify_articles...")
        classify_kwargs = {"limit": limit_classify}
        if date_from:
            self._validate_date(date_from)
            classify_kwargs["date_from"] = date_from
        if date_to:
            self._validate_date(date_to)
            classify_kwargs["date_to"] = date_to
        call_command("classify_articles", **classify_kwargs)

        self.stdout.write(self.style.SUCCESS("Pipeline completo"))

    def _validate_date(self, value: str) -> None:
        datetime.strptime(value, "%Y-%m-%d")
