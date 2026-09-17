from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0015_alter_episode_status"),
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
                    ("rejected", "Rejected — Video Too Long"),
                    ("failed", "Upload Failed"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
    ]
