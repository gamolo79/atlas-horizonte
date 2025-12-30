from django.core.management.base import BaseCommand

from monitor.models import JobLog
from monitor.pipeline import aggregate_metrics


class Command(BaseCommand):
    help = "Recalcula métricas agregadas para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--period", type=str, default="day")

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_aggregate", status="running")
        updated = aggregate_metrics(period=options["period"])
        job.status = "success"
        job.payload = {"aggregates": updated}
        job.save(update_fields=["status", "payload"])
        self.stdout.write(self.style.SUCCESS(f"Agregados {updated} registros"))
