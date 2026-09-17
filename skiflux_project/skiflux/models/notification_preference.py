from django.db import models


class UserNotificationPreferences(models.Model):
    user = models.OneToOneField(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )

    # Activity
    new_episodes = models.BooleanField(default=True)
    task_updates = models.BooleanField(default=True)
    comment_replies = models.BooleanField(default=True)
    comment_likes = models.BooleanField(default=True)

    # Coins & Rewards
    coin_earnings = models.BooleanField(default=True)
    badges = models.BooleanField(default=True)

    # Platform
    platform_announcements = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Notification Preferences"

    def __str__(self):
        return f"{self.user.email} notification preferences"

    @classmethod
    def get_or_create_for_user(cls, user):
        prefs, _ = cls.objects.get_or_create(user=user)
        return prefs

    def allows(self, event_type: str) -> bool:
        """
        Check if a specific event type is allowed
        based on user preferences.
        """
        mapping = {
            # new episode from followed creator
            "followed_creator_new_episode": "new_episodes",
            "new_season_from_followed_creator": "new_episodes",
            # task updates
            "task_approved_with_coins": "task_updates",
            "task_rejected_with_feedback": "task_updates",
            "task_submission_received": "task_updates",
            "task_reminder": "task_updates",
            "task_deadline_approaching": "task_updates",
            # comment
            "new_comment_on_episode": "comment_replies",
            "comment_liked": "comment_likes",
            # coins & rewards
            "deposit_confirmed": "coin_earnings",
            "withdrawal_processed": "coin_earnings",
            "referral_bonus_credited": "coin_earnings",
            # badges
            "milestone_badge_earned": "badges",
            "assessment_perfect_score": "badges",
            "streak_maintained": "badges",
            # platform
            "platform_announcement": "platform_announcements",
            "new_learning_path": "platform_announcements",
            "community_challenge": "platform_announcements",
        }
        pref_field = mapping.get(event_type)
        if not pref_field:
            return True  # unknown event types default to allowed
        return getattr(self, pref_field, True)
