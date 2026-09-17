from datetime import date, timedelta

from django.utils import timezone
from skiflux.models import User
from skiflux.models.platform_settings import SystemGamificationConfig
from skiflux.repositories.user_repository import UserRepository

WEEKDAY_LABELS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
MILESTONE_INTERVAL_DAYS = 7


def _ordinal(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _format_week_label(week_start: date, week_end: date) -> str:
    if week_start.month == week_end.month:
        return (
            f"{week_start.strftime('%b')} {_ordinal(week_start.day)} - "
            f"{_ordinal(week_end.day)}"
        )
    return (
        f"{week_start.strftime('%b')} {_ordinal(week_start.day)} - "
        f"{week_end.strftime('%b')} {_ordinal(week_end.day)}"
    )


def _calendar_week_bounds(for_date: date) -> tuple[date, date]:
    days_since_sunday = (for_date.weekday() + 1) % 7
    week_start = for_date - timedelta(days=days_since_sunday)
    return week_start, week_start + timedelta(days=6)


def _effective_streak_count(user: User, today: date) -> int:
    if not user.last_active_date:
        return 0
    if user.last_active_date < today - timedelta(days=1):
        return 0
    return user.streak_count


def _current_streak_active_dates(user: User, today: date) -> set[date]:
    streak_count = _effective_streak_count(user, today)
    if streak_count <= 0 or not user.last_active_date:
        return set()
    return {
        user.last_active_date - timedelta(days=offset) for offset in range(streak_count)
    }


def _day_status(day: date, today: date, active_dates: set[date]) -> str:
    if day in active_dates:
        return "completed"
    if day >= today:
        return "upcoming"
    return "missed"


class GamificationService:
    def __init__(self):
        self.user_repo = UserRepository()

    def determine_level(self, xp: int) -> str:
        config = SystemGamificationConfig.get_config()
        if xp >= config.xp_for_professional:
            return "professional"
        elif xp >= config.xp_for_expert:
            return "expert"
        elif xp >= config.xp_for_senior:
            return "senior"
        elif xp >= config.xp_for_amateur:
            return "amateur"
        return "novice"

    def process_daily_activity(self, user: User) -> None:
        today = timezone.localdate()

        if user.last_active_date == today:
            return  # Already processed for today

        config = SystemGamificationConfig.get_config()

        if user.last_active_date == today - timezone.timedelta(days=1):
            # Streak continues
            user.streak_count += 1
        elif (
            user.last_active_date is None
            or user.last_active_date < today - timezone.timedelta(days=1)
        ):
            # Streak broken or first day
            user.streak_count = 1

        user.last_active_date = today

        if user.streak_count > user.best_streak_count:
            user.best_streak_count = user.streak_count

        if user.streak_count > 0 and user.streak_count % MILESTONE_INTERVAL_DAYS == 0:
            user.xp += config.xp_per_7_day_streak
            user.total_streak_xp_earned += config.xp_per_7_day_streak

        user.current_level = self.determine_level(user.xp)
        self.user_repo.update(
            user,
            xp=user.xp,
            current_level=user.current_level,
            streak_count=user.streak_count,
            last_active_date=user.last_active_date,
            best_streak_count=user.best_streak_count,
            total_streak_xp_earned=user.total_streak_xp_earned,
        )

    def add_xp(self, user: User, xp_amount: int) -> User:
        user.xp += xp_amount
        user.current_level = self.determine_level(user.xp)
        return self.user_repo.update(user, xp=user.xp, current_level=user.current_level)

    def get_user_badges(self, user: User) -> list:
        from skiflux.models.gamification import UserBadge

        return list(UserBadge.objects.filter(user=user).select_related("badge"))

    def get_streak_summary(self, user: User) -> dict:
        user.refresh_from_db()
        self.process_daily_activity(user)

        today = timezone.localdate()
        config = SystemGamificationConfig.get_config()
        week_start, week_end = _calendar_week_bounds(today)
        active_dates = _current_streak_active_dates(user, today)
        current_streak_count = _effective_streak_count(user, today)
        best_streak = max(user.best_streak_count, current_streak_count)

        if (
            current_streak_count > 0
            and current_streak_count % MILESTONE_INTERVAL_DAYS == 0
        ):
            days_remaining = 0
            next_milestone_at = current_streak_count + MILESTONE_INTERVAL_DAYS
        else:
            days_remaining = (
                MILESTONE_INTERVAL_DAYS
                - (current_streak_count % MILESTONE_INTERVAL_DAYS)
                if current_streak_count > 0
                else MILESTONE_INTERVAL_DAYS
            )
            next_milestone_at = (
                (current_streak_count // MILESTONE_INTERVAL_DAYS) + 1
            ) * MILESTONE_INTERVAL_DAYS

        week_days = []
        for offset in range(MILESTONE_INTERVAL_DAYS):
            day = week_start + timedelta(days=offset)
            week_days.append(
                {
                    "weekday": WEEKDAY_LABELS[offset],
                    "date": day.isoformat(),
                    "day_of_month": day.day,
                    "status": _day_status(day, today, active_dates),
                }
            )

        return {
            "current_streak_count": current_streak_count,
            "is_streak_active": current_streak_count > 0,
            "best_streak": best_streak,
            "total_streak_xp_earned": user.total_streak_xp_earned,
            "week": {
                "start_date": week_start.isoformat(),
                "end_date": week_end.isoformat(),
                "label": _format_week_label(week_start, week_end),
                "days": week_days,
            },
            "milestone": {
                "interval_days": MILESTONE_INTERVAL_DAYS,
                "xp_reward": config.xp_per_7_day_streak,
                "next_at_streak": next_milestone_at,
                "days_remaining": days_remaining,
                "reached_today": (
                    current_streak_count > 0
                    and current_streak_count % MILESTONE_INTERVAL_DAYS == 0
                    and user.last_active_date == today
                ),
            },
        }
