"""
Activity Logger utility for easy activity logging throughout the application.
Use this to log activities from services, views, or tasks.
"""

from skiflux.services.activity import ActivityService
from skiflux.models.activity import ActivityLog


class ActivityLogger:
    """
    Convenient utility for logging activities across the application.
    Use this instead of directly calling ActivityService in most cases.

    Examples:
        # Log user verification
        ActivityLogger.user_verified(user_instance, admin_actor)

        # Log admin action
        ActivityLogger.admin_created(new_admin, created_by_admin)

        # Log custom activity
        ActivityLogger.log(
            action_type=ActivityLog.ActionType.TRANSACTION_COMPLETED,
            description="Payment received",
            subject=user,
            metadata={"amount": 5000, "currency": "NGN"}
        )
    """

    @staticmethod
    def log(action_type, description, actor=None, subject=None, metadata=None):
        """
        Generic activity logging method.

        Args:
            action_type: ActivityLog.ActionType choice
            description: Human-readable description
            actor: User performing the action
            subject: User affected by the action
            metadata: Additional context dict
        """
        return ActivityService.log_activity(
            action_type=action_type,
            description=description,
            actor=actor,
            subject=subject,
            metadata=metadata,
        )

    # User-related activities

    @staticmethod
    def user_created(user, actor=None):
        """Log when a user is created"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.USER_CREATED,
            description=f"User account created: {user.email}",
            subject=user,
            actor=actor,
        )

    @staticmethod
    def user_verified(user, actor=None):
        """Log when a user is verified"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.USER_VERIFIED,
            description=f"User verified: {user.email}",
            subject=user,
            actor=actor,
        )

    @staticmethod
    def user_promoted(user, new_role, old_role=None, actor=None):
        """Log when a user is promoted"""
        description = f"User promoted to {new_role}: {user.email}"
        metadata = {"new_role": new_role, "old_role": old_role}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.USER_PROMOTED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )

    @staticmethod
    def user_role_changed(user, new_role, old_role, actor=None):
        """Log when a user's role changes"""
        description = f"User role changed from {old_role} to {new_role}: {user.email}"
        metadata = {"new_role": new_role, "old_role": old_role}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.USER_ROLE_CHANGED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )

    # Admin-related activities

    @staticmethod
    def admin_created(admin, actor=None):
        """Log when an admin is created"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.ADMIN_CREATED,
            description=f"Admin account created: {admin.email}",
            subject=admin,
            actor=actor,
        )

    @staticmethod
    def admin_deactivated(admin, actor=None):
        """Log when an admin is deactivated"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.ADMIN_DEACTIVATED,
            description=f"Admin deactivated: {admin.email}",
            subject=admin,
            actor=actor,
        )

    # Verification-related activities

    @staticmethod
    def verification_approved(user, verification_type, actor=None):
        """Log when a user's verification is approved"""
        description = (
            f"Creator verification approved: {user.email} ({verification_type})"
        )
        metadata = {"verification_type": verification_type}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.VERIFICATION_APPROVED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )

    @staticmethod
    def verification_rejected(user, verification_type, reason=None, actor=None):
        """Log when a user's verification is rejected"""
        description = (
            f"Creator verification rejected: {user.email} ({verification_type})"
        )
        metadata = {"verification_type": verification_type, "reason": reason}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.VERIFICATION_REJECTED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )

    # Content-related activities

    @staticmethod
    def content_approved(content_type, content_id, actor=None, subject=None):
        """Log when content is approved"""
        description = f"{content_type} approved (ID: {content_id})"
        metadata = {"content_type": content_type, "content_id": content_id}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.CONTENT_APPROVED,
            description=description,
            actor=actor,
            subject=subject,
            metadata=metadata,
        )

    @staticmethod
    def content_rejected(
        content_type, content_id, reason=None, actor=None, subject=None
    ):
        """Log when content is rejected"""
        description = f"{content_type} rejected (ID: {content_id})"
        metadata = {
            "content_type": content_type,
            "content_id": content_id,
            "reason": reason,
        }
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.CONTENT_REJECTED,
            description=description,
            actor=actor,
            subject=subject,
            metadata=metadata,
        )

    # System alerts

    @staticmethod
    def suspicious_activity_detected(description, metadata=None):
        """Log suspicious activity"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.SUSPICIOUS_ACTIVITY,
            description=description,
            metadata=metadata,
        )

    @staticmethod
    def system_error(error_message, metadata=None):
        """Log system errors"""
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.SYSTEM_ERROR,
            description=error_message,
            metadata=metadata,
        )

    # Payment/Financial activities

    @staticmethod
    def transaction_completed(user, amount, currency, reference=None, actor=None):
        """Log completed transaction"""
        description = f"Transaction completed: {amount} {currency} - {reference}"
        metadata = {"amount": amount, "currency": currency, "reference": reference}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.TRANSACTION_COMPLETED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )

    @staticmethod
    def payment_failed(user, amount, currency, reason=None, actor=None):
        """Log failed payment"""
        description = f"Payment failed: {amount} {currency}"
        metadata = {"amount": amount, "currency": currency, "reason": reason}
        return ActivityLogger.log(
            action_type=ActivityLog.ActionType.PAYMENT_FAILED,
            description=description,
            subject=user,
            actor=actor,
            metadata=metadata,
        )
