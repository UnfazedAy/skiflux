from django.db import migrations, models

MILESTONE_INTERVAL_DAYS = 7


def _longest_streak_from_dates(dates):
    if not dates:
        return 0
    best = 1
    current = 1
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days == 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def _total_streak_xp_from_dates(dates, xp_per_milestone):
    if not dates:
        return 0

    total_xp = 0
    segment_length = 1
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days == 1:
            segment_length += 1
        else:
            total_xp += (segment_length // MILESTONE_INTERVAL_DAYS) * xp_per_milestone
            segment_length = 1
    total_xp += (segment_length // MILESTONE_INTERVAL_DAYS) * xp_per_milestone
    return total_xp


def backfill_user_streak_stats(apps, schema_editor):
    User = apps.get_model("skiflux", "User")
    UserBehaviourLog = apps.get_model("skiflux", "UserBehaviourLog")
    try:
        config = apps.get_model("skiflux", "SystemGamificationConfig").objects.first()
    except LookupError:
        config = None

    xp_per_milestone = getattr(config, "xp_per_7_day_streak", 50) if config else 50

    for user in User.objects.all().iterator():
        activity_dates = sorted(
            set(
                UserBehaviourLog.objects.filter(user_id=user.id).values_list(
                    "created_at__date", flat=True
                )
            )
        )
        best_from_logs = _longest_streak_from_dates(activity_dates)
        best_streak_count = max(user.streak_count, best_from_logs)
        gamification_xp_estimate = (
            user.streak_count // MILESTONE_INTERVAL_DAYS
        ) * xp_per_milestone
        total_streak_xp_earned = max(
            _total_streak_xp_from_dates(activity_dates, xp_per_milestone),
            gamification_xp_estimate,
        )

        if (
            user.best_streak_count != best_streak_count
            or user.total_streak_xp_earned != total_streak_xp_earned
        ):
            user.best_streak_count = best_streak_count
            user.total_streak_xp_earned = total_streak_xp_earned
            user.save(update_fields=["best_streak_count", "total_streak_xp_earned"])


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0091_alter_userplatformtask_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="best_streak_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="user",
            name="total_streak_xp_earned",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(
            backfill_user_streak_stats,
            migrations.RunPython.noop,
        ),
    ]
