import uuid

from django.db import models
from django.utils import timezone

from .content import EpisodeComment
from .user import User
from .admin_user import AdminUser


class CommentReport(models.Model):
    class Category(models.TextChoices):
        TOXIC_LANGUAGE = "toxic_language", "Toxic / Offensive language"
        SPAM = "spam", "Spam / External promotion"
        HARASSMENT = "harassment", "Harassment"
        INAPPROPRIATE_SOLICITATION = (
            "inappropriate_solicitation",
            "Inappropriate solicitation",
        )
        DUPLICATE = "duplicate", "Duplicate report"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    comment = models.ForeignKey(
        EpisodeComment,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    reported_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="comment_reports",
    )
    category = models.CharField(max_length=50, choices=Category.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("comment", "reported_by")]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["comment", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.reported_by} reported comment {self.comment_id} — {self.category}"
        )


class UserSuspension(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        LIFTED = "lifted", "Lifted"
        EXPIRED = "expired", "Expired"

    class SuspendedBySource(models.TextChoices):
        ADMIN = "admin", "Admin"
        AI = "ai", "Moderator (Auto)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="suspensions",
    )
    suspended_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_suspensions",
    )
    source = models.CharField(
        max_length=10,
        choices=SuspendedBySource.choices,
        default=SuspendedBySource.ADMIN,
    )
    reason = models.CharField(max_length=255)
    duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of days. Null means permanent / until further notice.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Null means permanent.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    lifted_by = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifted_suspensions",
    )
    lifted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    @property
    def is_permanent(self) -> bool:
        return self.duration_days is None

    @property
    def display_duration(self) -> str:
        if self.is_permanent:
            return "Permanent"
        return f"{self.duration_days}d"

    def is_expired(self) -> bool:
        if self.is_permanent:
            return False
        return self.expires_at and timezone.now() >= self.expires_at

    def __str__(self):
        return f"{self.user} suspended {self.display_duration} — {self.status}"


class ModerationActionLog(models.Model):
    class ActionType(models.TextChoices):
        COMMENT_DELETED = "comment_deleted", "Comment Deleted"
        WARNING_ISSUED = "warning_issued", "Warning Issued"
        SUSPENSION = "suspension", "Suspension"
        DEACTIVATION = "deactivation", "Deactivation"
        REPORT_DISMISSED = "report_dismissed", "Report Dismissed"
        SUSPENSION_LIFTED = "suspension_lifted", "Suspension Lifted"
        AI_FLAGGED = "ai_flagged", "Flagged by AI Moderator"

    class Source(models.TextChoices):
        ADMIN = "admin", "Admin"
        AI = "ai", "AI Auto-moderation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.ADMIN,
    )
    performed_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_actions",
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_history",
    )
    comment = models.ForeignKey(
        EpisodeComment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    reason = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra context e.g. suspension duration, AI confidence score.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action_type"]),
            models.Index(fields=["target_user"]),
            models.Index(fields=["performed_by"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.action_type} on {self.target_user} by {self.performed_by}"
