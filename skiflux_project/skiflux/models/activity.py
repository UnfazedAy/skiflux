"""
Activity log model for tracking major system actions.
Provides flexible activity tracking with extensible action types.
"""

from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    """
    Tracks major actions across the system for audit and visibility.
    Supports flexible action types that can be extended as needed.
    """

    class ActionType(models.TextChoices):
        """Predefined action types - easily extendable"""

        # User actions
        USER_CREATED = "user_created", "User Created"
        USER_VERIFIED = "user_verified", "User Verified"
        USER_PROMOTED = "user_promoted", "User Promoted"
        USER_ROLE_CHANGED = "user_role_changed", "User Role Changed"
        USER_DEACTIVATED = "user_deactivated", "User Deactivated"
        USER_REACTIVATED = "user_reactivated", "User Reactivated"

        # Admin actions
        ADMIN_CREATED = "admin_created", "Admin Created"
        ADMIN_DEACTIVATED = "admin_deactivated", "Admin Deactivated"
        ADMIN_SUSPENDED = "admin_suspended", "Admin Suspended"
        ADMIN_UNSUSPENDED = "admin_unsuspended", "Admin Unsuspended"
        ADMIN_ROLE_CHANGED = "admin_role_changed", "Admin Role Changed"

        # Verification actions
        VERIFICATION_APPROVED = "verification_approved", "Verification Approved"
        VERIFICATION_REJECTED = "verification_rejected", "Verification Rejected"

        # Content actions
        CONTENT_REJECTED = "content_rejected", "Content Rejected"
        CONTENT_APPROVED = "content_approved", "Content Approved"
        EPISODE_PUBLISHED = "episode_published", "Episode Published"
        EPISODE_UNPUBLISHED = "episode_unpublished", "Episode Unpublished"
        EPISODE_UPDATED = "episode_updated", "Episode Updated"
        EPISODE_REMOVED = "episode_removed", "Episode Removed"
        SEASON_PUBLISHED = "season_published", "Season Published"
        SEASON_UNPUBLISHED = "season_unpublished", "Season Unpublished"
        SEASON_UPDATED = "season_updated", "Season Updated"
        SEASON_REMOVED = "season_removed", "Season Removed"

        # System alerts
        SUSPICIOUS_ACTIVITY = "suspicious_activity", "Suspicious Activity Detected"
        SYSTEM_ERROR = "system_error", "System Error"

        # Payment/Financial
        TRANSACTION_COMPLETED = "transaction_completed", "Transaction Completed"
        PAYMENT_FAILED = "payment_failed", "Payment Failed"
        WALLET_ADJUSTED = "wallet_adjusted", "Wallet Adjusted"
        WALLET_LOCKED = "wallet_locked", "Wallet Locked"
        WALLET_UNLOCKED = "wallet_unlocked", "Wallet Unlocked"
        REFUND_ISSUED = "refund_issued", "Refund Issued"
        FINANCIAL_CONFIG_UPDATED = (
            "financial_config_updated",
            "Financial Config Updated",
        )
        WITHDRAWAL_PROCESSED = "withdrawal_processed", "Withdrawal Processed"

        # Moderation actions
        MODERATION_WARNING_ISSUED = (
            "moderation_warning_issued",
            "Moderation Warning Issued",
        )
        MODERATION_SUSPENSION = "moderation_suspension", "Moderation Suspension"
        MODERATION_SUSPENSION_LIFTED = (
            "moderation_suspension_lifted",
            "Moderation Suspension Lifted",
        )
        MODERATION_COMMENT_REPORTED = (
            "moderation_comment_reported",
            "Moderation Comment Reported",
        )
        MODERATION_COMMENT_REMOVED = (
            "moderation_comment_removed",
            "Moderation Comment Removed",
        )
        MODERATION_REPORT_DISMISSED = (
            "moderation_report_dismissed",
            "Moderation Report Dismissed",
        )

    # Core fields
    action_type = models.CharField(
        max_length=50, choices=ActionType.choices, help_text="Type of action performed"
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiated_activities",
        help_text="Learner/user who performed the action, when applicable.",
    )
    actor_admin = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiated_activities",
        help_text="Admin who performed the action, when applicable.",
    )
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subject_activities",
        help_text="Learner/user who is the subject of the action, when applicable.",
    )
    subject_admin = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subject_activities",
        help_text="Admin/creator who is the subject of the action, when applicable.",
    )

    # Flexible metadata storage for any additional context
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context about the activity (e.g old/new values, reason)",
    )

    description = models.TextField(
        help_text="Human-readable description of the activity"
    )

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["action_type", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.get_action_type_display()} - {self.timestamp}"
