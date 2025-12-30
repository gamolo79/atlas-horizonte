from django.core.management.base import BaseCommand

from monitor.models import JobLog
from monitor.pipeline import ingest_sources


class Command(BaseCommand):
    help = "Ingesta de fuentes para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_ingest", status="running")
        articles = ingest_sources(limit=options["limit"])
        job.status = "success"
        job.payload = {"created": len(articles)}
        job.save(update_fields=["status", "payload"])
        self.stdout.write(self.style.SUCCESS(f"Ingestadas {len(articles)} notas"))
