from django.core.management.base import BaseCommand

from monitor.models import JobLog
from monitor.pipeline import cluster_stories


class Command(BaseCommand):
    help = "Agrupa artículos en historias para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_cluster", status="running")
        stories = cluster_stories(hours=options["hours"])
        job.status = "success"
        job.payload = {"stories": stories}
        job.save(update_fields=["status", "payload"])
        self.stdout.write(self.style.SUCCESS(f"Creadas {stories} historias"))
