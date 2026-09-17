from django.db import migrations, models


def backfill_follow_notification_mode(apps, schema_editor):
    Follow = apps.get_model("skiflux", "Follow")
    Follow.objects.filter(notifications_enabled=False).update(notification_mode="none")
    Follow.objects.filter(notifications_enabled=True).update(notification_mode="all")


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0100_user_app_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="follow",
            name="notification_mode",
            field=models.CharField(
                choices=[
                    ("all", "All updates"),
                    ("personalized", "Personalized"),
                    ("none", "None"),
                ],
                default="all",
                help_text="Per-creator notification mode for followed creators.",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            backfill_follow_notification_mode,
            migrations.RunPython.noop,
        ),
    ]
