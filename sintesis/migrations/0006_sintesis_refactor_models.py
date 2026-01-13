from datetime import time

from django.db import migrations, models
from django.utils import timezone


def set_schedule_defaults(apps, schema_editor):
    SynthesisSchedule = apps.get_model("sintesis", "SynthesisSchedule")
    for schedule in SynthesisSchedule.objects.all():
        if schedule.run_at:
            run_at = schedule.run_at
            schedule.run_time = run_at.timetz().replace(tzinfo=None)
            schedule.window_start_time = time(0, 0)
            schedule.window_end_time = run_at.timetz().replace(tzinfo=None)
            schedule.next_run_at = run_at
        if not schedule.next_run_at:
            schedule.next_run_at = timezone.now()
        if not schedule.days_of_week:
            schedule.days_of_week = list(range(7))
        if not schedule.timezone:
            schedule.timezone = "America/Mexico_City"
        schedule.save()


def backfill_story_fingerprint(apps, schema_editor):
    SynthesisStory = apps.get_model("sintesis", "SynthesisStory")
    for story in SynthesisStory.objects.all():
        if not story.story_fingerprint:
            story.story_fingerprint = f"legacy-{story.id}"
            story.save(update_fields=["story_fingerprint"])


class Migration(migrations.Migration):

    dependencies = [
        ("sintesis", "0005_remove_synthesissectionfilter_note_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="synthesissectiontemplate",
            name="section_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synthesissectionfilter",
            name="keywords_json",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="timezone",
            field=models.CharField(default="America/Mexico_City", max_length=80),
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="run_time",
            field=models.TimeField(default=time(8, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="window_start_time",
            field=models.TimeField(default=time(0, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="window_end_time",
            field=models.TimeField(default=time(12, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="days_of_week",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="next_run_at",
            field=models.DateTimeField(default=timezone.now, db_index=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="synthesisschedule",
            name="last_run_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="parent_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="versions",
                to="sintesis.synthesisrun",
            ),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="regeneration_scope",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="regenerated_template_id",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="review_text",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="window_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synthesisrun",
            name="window_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="synthesisstory",
            name="story_fingerprint",
            field=models.CharField(db_index=True, default="", max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="synthesisrunsection",
            name="review_text",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synthesisrunsection",
            name="prompt_snapshot",
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(set_schedule_defaults, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(backfill_story_fingerprint, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="synthesisschedule",
            name="run_at",
        ),
        migrations.AlterModelOptions(
            name="synthesisschedule",
            options={"ordering": ["-next_run_at"]},
        ),
        migrations.AddConstraint(
            model_name="synthesisstory",
            constraint=models.UniqueConstraint(
                fields=("run", "story_fingerprint"),
                name="unique_story_fingerprint_per_run",
            ),
        ),
    ]
