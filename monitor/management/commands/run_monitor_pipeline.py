from django.core.management.base import BaseCommand

from monitor.pipeline import run_pipeline

class Command(BaseCommand):
    help = "Runs the full Monitor 2.0 pipeline: Ingest -> AI Classify -> Link -> Cluster -> Synthesis."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--model", type=str, default="gpt-4o-mini")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no se ejecuta el pipeline."))
            return
        run_pipeline(hours=opts["hours"], limit=opts["limit"])
