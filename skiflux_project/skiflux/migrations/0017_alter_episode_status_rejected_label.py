from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0016_episode_processing_failed_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="episode",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("processing", "Processing"),
                    ("published", "Published"),
                    ("rejected", "Rejected"),
                    ("failed", "Upload Failed"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
    ]
