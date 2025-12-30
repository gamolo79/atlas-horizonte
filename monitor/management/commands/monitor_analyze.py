from django.core.management.base import BaseCommand

from monitor.models import Article, JobLog
from monitor.pipeline import classify_articles, normalize_articles


class Command(BaseCommand):
    help = "Normaliza y clasifica artículos para Monitor Horizonte."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        job = JobLog.objects.create(job_name="monitor_analyze", status="running")
        articles = list(Article.objects.order_by("-published_at")[: options["limit"]])
        normalize_articles(articles)
        processed = classify_articles(articles)
        job.status = "success"
        job.payload = {"processed": processed}
        job.save(update_fields=["status", "payload"])
        self.stdout.write(self.style.SUCCESS(f"Clasificadas {processed} notas"))
