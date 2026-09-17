import uuid

from django.db import models


class PlatformAnnouncement(models.Model):
    class SendType(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        DAILY = "daily", "Daily Recurring"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_announcements",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    image_public_id = models.CharField(max_length=255, blank=True, null=True)
    send_type = models.CharField(
        max_length=20,
        choices=SendType.choices,
        default=SendType.IMMEDIATE,
        help_text="immediate or daily recurring",
    )
    daily_send_time = models.TimeField(null=True, blank=True)
    delivery_channel = models.CharField(
        max_length=20,
        choices=[
            ("foreground", "Foreground"),
            ("background", "Background"),
        ],
        default="foreground",
    )
    audience = models.CharField(max_length=255, blank=True, default="All users")
    last_sent_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_platform_announcement"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.send_type})"


class Notification(models.Model):
    class Type(models.TextChoices):
        PLATFORM_ANNOUNCEMENT = "platform_announcement", "Platform Announcement"
        TASK_REMINDER = "task_reminder", "Task Reminder"
        FOLLOWED_CREATOR_NEW_EPISODE = (
            "followed_creator_new_episode",
            "Followed Creator New Episode",
        )
        WE_MISS_YOU = "we_miss_you", "We Miss You Reminder"
        NEW_COMMENT_ON_EPISODE = "new_comment_on_episode", "New Comment on My Episode"
        MILESTONE_BADGE_EARNED = "milestone_badge_earned", "Milestone Badge Earned"
        NEW_FOLLOWER = "new_follower", "New Follower (for Creators)"
        ASSESSMENT_PERFECT_SCORE = (
            "assessment_perfect_score",
            "Assessment Perfect Score",
        )
        NEW_SEASON_FROM_FOLLOWED_CREATOR = (
            "new_season_from_followed_creator",
            "New Season from Followed Creator",
        )
        TASK_DEADLINE_APPROACHING = (
            "task_deadline_approaching",
            "Task Deadline Approaching",
        )
        REFERRAL_BONUS_CREDITED = "referral_bonus_credited", "Referral Bonus Credited"
        STREAK_BROKEN = "streak_broken", "Streak Broken"
        STREAK_MAINTAINED = "streak_maintained", "Streak Maintained"
        EPISODE_REACHED_X_VIEWS = "episode_reached_x_views", "Episode Reached X Views"
        REVENUE_MILESTONE = "revenue_milestone", "Creator Revenue Milestone"
        NEW_LEARNING_PATH = "new_learning_path", "New Learning Path Available"
        COMMUNITY_CHALLENGE = "community_challenge", "Community Challenge"
        MODERATION_WARNING = "moderation_warning", "Moderation Warning"
        MODERATION_SUSPENSION = "moderation_suspension", "Moderation Suspension"
        MODERATION_SUSPENSION_LIFTED = (
            "moderation_suspension_lifted",
            "Suspension Lifted",
        )
        COMMENT_REMOVED = "comment_removed", "Comment Removed"

    class DeliveryChannel(models.TextChoices):
        FOREGROUND = "foreground", "Foreground"
        BACKGROUND = "background", "Background"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=50, choices=Type.choices)
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    delivery_channel = models.CharField(
        max_length=20,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.FOREGROUND,
    )
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.SENT,
    )
    audience = models.CharField(max_length=255, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skiflux_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["admin_user", "is_read"]),
            models.Index(fields=["type", "created_at"]),
            models.Index(fields=["delivery_channel", "delivery_status"]),
            models.Index(fields=["delivery_status", "scheduled_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(user__isnull=False) & models.Q(admin_user__isnull=True))
                    | (models.Q(user__isnull=True) & models.Q(admin_user__isnull=False))
                ),
                name="notification_must_have_exactly_one_recipient",
            ),
        ]

    def __str__(self):
        recipient = self.user or self.admin_user
        return f"{self.type} for {recipient} - {self.title[:30]}"
