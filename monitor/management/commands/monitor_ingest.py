from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import JobLog
from monitor.pipeline import ingest_sources


class Command(BaseCommand):
    help = "Ingesta de fuentes para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_ingest", status="running")
        try:
            result = ingest_sources(limit=options["limit"])
            status = "success" if result.stats.get("errors", 0) == 0 else "partial"
            job.status = status
            job.payload = result.stats
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "payload", "finished_at"])
            self.stdout.write(self.style.SUCCESS(f"Ingestadas {len(result.articles)} notas"))
        except Exception as exc:
            job.status = "error"
            job.payload = {"error": str(exc)}
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "payload", "finished_at"])
            self.stdout.write(self.style.ERROR(f"Fallo ingesta: {exc}"))
