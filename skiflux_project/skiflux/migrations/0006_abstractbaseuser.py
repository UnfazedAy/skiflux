from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0005_alter_user_avatar_url_alter_user_goal"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_login",
            field=models.DateTimeField(
                null=True, blank=True, verbose_name="last login"
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="is_staff",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="is_superuser",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="user",
            index=models.Index(
                fields=["auth_provider", "social_id"], name="idx_user_social"
            ),
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX idx_user_username_ci
                ON skiflux_user (UPPER(username))
                WHERE username IS NOT NULL;
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_user_username_ci;",
        ),
    ]
