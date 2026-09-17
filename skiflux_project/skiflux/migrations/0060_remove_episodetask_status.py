# Handwritten migration: remove the static `status` field from EpisodeTask.
# Status is now computed dynamically per-student from TaskSubmission /
# AssessmentSubmission records and is never persisted on the task itself.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0059_alter_usersuspension_duration_days"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="episodetask",
            name="status",
        ),
    ]
