from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0099_badge_icon_public_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAppPreferences",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("auto_play_next", models.BooleanField(default=True)),
                (
                    "download_quality",
                    models.CharField(
                        choices=[
                            ("high", "High"),
                            ("standard", "Standard"),
                            ("data_saver", "Data saver"),
                        ],
                        default="standard",
                        max_length=20,
                    ),
                ),
                ("download_on_wifi_only", models.BooleanField(default=True)),
                ("app_language", models.CharField(default="en", max_length=10)),
                ("save_watch_history", models.BooleanField(default=True)),
                ("personalised_recommendations", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="app_preferences",
                        to="skiflux.user",
                    ),
                ),
            ],
            options={
                "verbose_name": "User App Preferences",
                "db_table": "skiflux_user_app_preferences",
            },
        ),
    ]
