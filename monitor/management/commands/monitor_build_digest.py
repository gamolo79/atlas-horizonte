from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from monitor.models import JobLog
from monitor.pipeline import build_daily_digest


class Command(BaseCommand):
    help = "Construye la síntesis diaria para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default="")

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_build_digest", status="running")
        run_date = options["date"]
        date_value = parse_date(run_date) if run_date else None
        items = build_daily_digest(date=date_value)
        job.status = "success"
        job.payload = {"items": items}
        job.save(update_fields=["status", "payload"])
        self.stdout.write(self.style.SUCCESS(f"Generadas {items} entradas"))
