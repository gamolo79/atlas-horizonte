from datetime import date, datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from sintesis.models import SynthesisClient, SynthesisRun, SynthesisSchedule
from sintesis.run_builder import build_run, build_run_document, resolve_date_range


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Genera síntesis agrupadas por cliente."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, default=None)
        parser.add_argument("--schedule-id", type=int, default=None)
        parser.add_argument("--date-from", type=str, default=None)
        parser.add_argument("--date-to", type=str, default=None)
        parser.add_argument("--run-id", type=int, default=None)

    def handle(self, *args, **options):
        schedule_id = options.get("schedule_id")
        client_id = options.get("client_id")
        run_id = options.get("run_id")
        date_from = options.get("date_from")
        date_to = options.get("date_to")

        date_from, date_to = self._parse_dates(date_from, date_to)
        date_from, date_to = resolve_date_range(date_from, date_to)

        if run_id:
            run = SynthesisRun.objects.select_related("client").get(pk=run_id)
            self._process_run(run)
            return

        clients = SynthesisClient.objects.filter(is_active=True)
        schedule = None
        run_type = "manual"
        if schedule_id:
            schedule = SynthesisSchedule.objects.select_related("client").get(pk=schedule_id)
            client_id = schedule.client_id
            run_type = "scheduled"
        if client_id:
            clients = clients.filter(pk=client_id)

        for client in clients:
            self.stdout.write(f"Generando síntesis para {client.name}...")
            run = build_run(
                client=client,
                date_from=date_from,
                date_to=date_to,
                schedule=schedule,
                run_type=run_type,
                status="running",
            )
            count = self._process_run(run)
            self.stdout.write(self.style.SUCCESS(f"Síntesis generada ({count} historias)."))

    def _process_run(self, run):
        run.status = "running"
        run.error_message = ""
        run.save(update_fields=["status", "error_message"])
        status = "failed"
        error_message = ""
        try:
            count = build_run_document(run)
            status = "completed"
            return count
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            logger.exception("Error en run de síntesis %s.", run.pk)
            raise
        finally:
            run.status = status
            run.error_message = error_message
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])

    def _parse_dates(self, date_from, date_to):
        parsed_from = self._parse_date(date_from)
        parsed_to = self._parse_date(date_to)
        return parsed_from, parsed_to

    def _parse_date(self, value):
        if not value:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, str):
            return None
        try:
            return timezone.datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
