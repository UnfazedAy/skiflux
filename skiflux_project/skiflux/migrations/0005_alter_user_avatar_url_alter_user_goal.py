# skiflux/migrations/0005_alter_user_avatar_url_alter_user_goal.py

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "skiflux",
            "0004_user_goal_user_is_onboarded_user_skillworld_and_more",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="avatar_url",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        # 1. Delete the old Postgres Array column
        migrations.RemoveField(
            model_name="user",
            name="goal",
        ),
        # 2. Add it back as a fresh JSONB column
        migrations.AddField(
            model_name="user",
            name="goal",
            field=models.JSONField(
                blank=True,
                choices=[
                    ("build_portfolio", "Build a verified portfolio"),
                    ("learn_skill", "Learn a new technical skill"),
                    ("earn_income", "Earn income through tasks"),
                    ("network", "Network with creators"),
                ],
                default=list,
                null=True,
            ),
        ),
    ]
