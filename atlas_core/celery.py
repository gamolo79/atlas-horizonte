import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atlas_core.settings")

app = Celery("atlas_core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
