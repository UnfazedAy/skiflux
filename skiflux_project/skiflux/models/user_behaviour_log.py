from django.db import models

from .content import Episode, Season
from .user import User


class UserBehaviourLog(models.Model):
    class Action(models.TextChoices):
        VIEW = "view", "Viewed Episode"
        LIKE = "like", "Liked Episode"
        SAVE = "save", "Saved Episode"
        COMMENT = "comment", "Commented"
        TASK_ATTEMPT = "task_attempt", "Attempted Task"
        TASK_COMPLETE = "task_complete", "Completed Task"

    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="behaviour_logs",
    )
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="behaviour_logs",
        null=True,
    )
    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="behaviour_logs",
        null=True,
    )
    skillworld = models.CharField(
        max_length=50,
        choices=User.Skillworld.choices,
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    weight = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "skillworld"]),
            models.Index(fields=["user", "action"]),
        ]

    @classmethod
    def compute_current_streak(cls, user) -> int:
        recent = (
            cls.objects.filter(user=user)
            .values_list("created_at__date", flat=True)
            .distinct()
            .order_by("-created_at__date")[:30]
        )
        active_dates = sorted(set(recent), reverse=True)
        if not active_dates:
            return 0
        streak = 1
        prev = active_dates[0]
        for d in active_dates[1:]:
            if (prev - d).days == 1:
                streak += 1
                prev = d
            else:
                break
        return streak


class UserSkillworldScore(models.Model):
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="skillworld_scores",
    )
    skillworld = models.CharField(
        max_length=50,
        choices=User.Skillworld.choices,
    )
    total_weight = models.FloatField(default=0.0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "skillworld")]
        indexes = [
            models.Index(fields=["user", "total_weight"]),
        ]
