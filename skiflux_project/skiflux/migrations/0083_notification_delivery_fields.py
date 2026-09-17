from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0082_tasksubmission_file_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="audience",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="notification",
            name="delivery_channel",
            field=models.CharField(
                choices=[("foreground", "Foreground"), ("background", "Background")],
                default="foreground",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="delivery_status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("sent", "Sent")],
                default="sent",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="scheduled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformannouncement",
            name="audience",
            field=models.CharField(blank=True, default="All users", max_length=255),
        ),
        migrations.AddField(
            model_name="platformannouncement",
            name="delivery_channel",
            field=models.CharField(
                choices=[("foreground", "Foreground"), ("background", "Background")],
                default="foreground",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["delivery_channel", "delivery_status"],
                name="skiflux_not_deliver_8a1f2d_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["delivery_status", "scheduled_at"],
                name="skiflux_not_deliver_4c9e1a_idx",
            ),
        ),
    ]
