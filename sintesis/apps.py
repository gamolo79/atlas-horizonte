from django.apps import AppConfig
from django.db.models.signals import post_migrate


class SintesisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sintesis"

    def ready(self) -> None:
        from sintesis.signals import ensure_dispatch_schedule

        post_migrate.connect(ensure_dispatch_schedule, sender=self)
