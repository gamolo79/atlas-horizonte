from django.utils import timezone

from django_celery_beat.models import IntervalSchedule, PeriodicTask


def ensure_dispatch_schedule(**_kwargs):
    schedule, _ = IntervalSchedule.objects.get_or_create(every=1, period=IntervalSchedule.MINUTES)
    PeriodicTask.objects.get_or_create(
        name="dispatch_due_schedules",
        defaults={
            "interval": schedule,
            "task": "sintesis.tasks.dispatch_due_schedules",
            "start_time": timezone.now(),
        },
    )
