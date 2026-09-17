from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0098_auto_publish_seasons_with_published_episodes"),
    ]

    operations = [
        migrations.AddField(
            model_name="badge",
            name="icon_public_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
