from datetime import datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from sintesis.models import SynthesisRun
from sintesis.tasks import generate_synthesis_run


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Genera síntesis agrupadas por cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, default=None)
        parser.add_argument("--schedule-id", type=int, default=None)
        parser.add_argument("--window-start", type=str, default=None)
        parser.add_argument("--window-end", type=str, default=None)
        parser.add_argument("--run-id", type=int, default=None)

    def handle(self, *args, **options):
        schedule_id = options.get("schedule_id")
        client_id = options.get("client_id")
        run_id = options.get("run_id")
        window_start = options.get("window_start")
        window_end = options.get("window_end")

        if run_id:
            run = SynthesisRun.objects.get(pk=run_id)
            self.stdout.write(f"Regenerando HTML/PDF para run {run.id}")
            generate_synthesis_run(
                client_id=run.client_id,
                window_start=run.window_start.isoformat() if run.window_start else None,
                window_end=run.window_end.isoformat() if run.window_end else None,
            )
            return

        if not schedule_id and not client_id:
            self.stdout.write(self.style.ERROR("Debes especificar --client-id o --schedule-id"))
            return

        window_start_dt = self._parse_datetime(window_start)
        window_end_dt = self._parse_datetime(window_end)

        run_id = generate_synthesis_run(
            schedule_id=schedule_id,
            client_id=client_id,
            window_start=window_start_dt.isoformat() if window_start_dt else None,
            window_end=window_end_dt.isoformat() if window_end_dt else None,
        )
        self.stdout.write(self.style.SUCCESS(f"Síntesis generada (run #{run_id})."))

    def _parse_datetime(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return timezone.make_aware(value) if timezone.is_naive(value) else value
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
