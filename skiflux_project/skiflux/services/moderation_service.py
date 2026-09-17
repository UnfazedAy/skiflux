from django.db import transaction
from rest_framework.exceptions import ValidationError

from skiflux.models import AdminUser, User
from skiflux.models.content import EpisodeComment
from skiflux.models.moderation import (
    CommentReport,
    ModerationActionLog,
    UserSuspension,
)
from skiflux.repositories.moderation_repository import ModerationRepository
from skiflux.services.notification_service import NotificationService
from skiflux.services.activity import ActivityService
from skiflux.models.activity import ActivityLog
from skiflux.utils.emails import (
    send_warning_email,
    send_suspension_email,
    send_suspension_lifted_email,
)
from django.core.cache import cache
from skiflux.repositories.user_repository import UserRepository


class ModerationService:
    def __init__(self):
        self.repo = ModerationRepository()
        self.notification_service = NotificationService()
        self.activity_service = ActivityService()
        self.user_repo = UserRepository()

    def get_stats(self) -> dict:
        return self.repo.get_stats()

    def get_flagged_comments(self, skillworld: str = None):
        return self.repo.get_flagged_comments(skillworld=skillworld)

    def _get_comment_or_raise(self, comment_id: str) -> EpisodeComment:
        comment = self.repo.get_comment_by_id(comment_id)
        if not comment:
            raise ValidationError("Comment not found.")
        return comment

    def _get_flagged_comment_or_raise(self, comment_id: str) -> EpisodeComment:
        comment = self.repo.get_flagged_comment_by_id(comment_id)
        if not comment:
            raise ValidationError("Flagged comment not found.")
        return comment

    def _get_suspension_or_raise(self, suspension_id: str) -> UserSuspension:
        suspension = self.repo.get_suspension_by_id(suspension_id)
        if not suspension:
            raise ValidationError("Suspension not found.")
        return suspension

    def _get_suspension_or_raise_by_userId(self, user_id: str) -> UserSuspension:
        suspension = self.repo.get_suspension_by_userId(user_id)
        if not suspension:
            raise ValidationError("Suspension not found.")
        return suspension

    def delete_comment(
        self,
        comment_id: str,
        admin: AdminUser,
        reason: str = "",
    ) -> dict:
        comment = self._get_comment_or_raise(comment_id)

        with transaction.atomic():
            self.repo.resolve_reports_for_comment(comment_id)
            target_user = comment.user

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.COMMENT_DELETED,
                performed_by=admin,
                target_user=target_user,
                comment=comment,
                reason=reason,
            )
            self.repo.delete_comment(comment)

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_COMMENT_REMOVED,
            description=f"Comment {comment_id} deleted by {admin.email}",
            actor=admin,
            subject=target_user,
            metadata={
                "comment_id": comment.id,
                "episode_id": str(comment.episode_id),
                "reason": reason,
            },
        )

        # send in app notification
        self.notification_service.create_notification(
            user=target_user,
            type="moderation_comment_removed",
            title="Comment Removed",
            body=(
                "One of your comments has been removed by our moderation team. "
                "Reason: {reason}"
            ),
            data={"comment_id": comment.id},
        )

        return {"detail": "Comment deleted."}

    def warn_user(
        self,
        comment_id: str,
        admin: AdminUser,
        category: str,
        message: str,
    ) -> dict:
        comment = self._get_comment_or_raise(comment_id)
        user = comment.user

        with transaction.atomic():
            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.WARNING_ISSUED,
                performed_by=admin,
                target_user=user,
                comment=comment,
                reason=category,
                metadata={"message": message, "category": category},
            )

        # send email
        send_warning_email(
            email=user.email,
            category=category,
            message=message,
        )

        # send in-app notification
        self.notification_service.create_notification(
            user=user,
            type="moderation_warning",
            title="Community Guidelines Warning",
            body=message,
            data={"category": category},
        )

        self.notification_service.send_push_for_event(
            user=user,
            event_type="moderation_warning",
            title="Community Guidelines Warning",
            body=f"{message[:100]}" if len(message) > 100 else f"{message}",
            data={
                "category": category,
                "comment_id": comment.id,
                "type": "warning",
            },
        )

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
            description=f"Warning issued to {user.email} for {category}",
            actor=admin,
            subject=user,
            metadata={
                "comment_id": comment.id,
                "category": category,
                "message": message,
            },
        )

        return {"detail": "Warning issued."}

    def suspend_user(
        self,
        comment_id: str,
        admin: AdminUser,
        reason: str,
        duration_days: int | None,
    ) -> dict:
        comment = self._get_comment_or_raise(comment_id)
        user = comment.user

        if user.status == User.Status.SUSPENDED:
            raise ValidationError("User is already suspended.")

        with transaction.atomic():
            suspension = self.repo.create_suspension(
                user=user,
                suspended_by=admin,
                reason=reason,
                duration_days=duration_days,
            )

            self.repo.resolve_reports_for_comment(comment_id)
            self.repo.unflag_comment(comment)

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.SUSPENSION,
                performed_by=admin,
                target_user=user,
                comment=comment,
                reason=reason,
                metadata={
                    "duration_days": duration_days,
                    "expires_at": suspension.expires_at.isoformat()
                    if suspension.expires_at
                    else None,
                    "permanent": suspension.is_permanent,
                },
            )

        # send email
        send_suspension_email(
            email=user.email,
            reason=reason,
            duration_days=duration_days,
        )

        # send in-app notification
        self.notification_service.create_notification(
            user=user,
            type="moderation_suspension",
            title="Account Suspended",
            body=f"Your account has been suspended. Reason: {reason}",
            data={"duration_days": duration_days},
        )

        self.notification_service.send_push_for_event(
            user=user,
            event_type="moderation_suspension",
            title="Account Suspended",
            body=f"Your account has been suspended. Reason: {reason}",
            data={"duration_days": duration_days},
        )

        msg = (f"User {user.email} suspended for {duration_days or 'permanent'} days",)
        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_SUSPENSION,
            description=msg,
            actor=admin,
            subject=user,
            metadata={
                "comment_id": comment.id,
                "reason": reason,
                "duration_days": duration_days,
                "suspension_id": str(suspension.id),
            },
        )

        return {"detail": "User suspended.", "suspension_id": str(suspension.id)}

    def dismiss_report(
        self,
        comment_id: str,
        admin: AdminUser,
        reason: str = "",
    ) -> dict:
        comment = self._get_comment_or_raise(comment_id)

        with transaction.atomic():
            self.repo.dismiss_reports_for_comment(comment_id)
            self.repo.unflag_comment(comment)

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.REPORT_DISMISSED,
                performed_by=admin,
                target_user=comment.user,
                comment=comment,
                reason=reason,
            )

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_REPORT_DISMISSED,
            description=f"Report dismissed for comment {comment_id}",
            actor=admin,
            subject=comment.user,
            metadata={"comment_id": str(comment_id), "reason": reason},
        )

        return {"detail": "Report dismissed."}

    # ─────────────────────────────────────────
    # All Comments
    # ─────────────────────────────────────────

    def get_all_comments(
        self,
        search: str = None,
        filter_type: str = None,
        skillworld: str = None,
    ):
        return self.repo.get_all_comments(
            search=search,
            filter_type=filter_type,
            skillworld=skillworld,
        )

    # ─────────────────────────────────────────
    # Suspensions
    # ─────────────────────────────────────────

    def get_active_suspensions(self, skillworld: str = None):
        return self.repo.get_active_suspensions(skillworld=skillworld)

    def lift_suspension(
        self,
        suspension_id: str,
        admin: AdminUser,
    ) -> dict:
        suspension = self._get_suspension_or_raise(suspension_id)

        if suspension.status != UserSuspension.Status.ACTIVE:
            raise ValidationError(f"Suspension is already {suspension.status}.")

        with transaction.atomic():
            suspension = self.repo.lift_suspension(
                suspension=suspension,
                lifted_by=admin,
            )

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.SUSPENSION_LIFTED,
                performed_by=admin,
                target_user=suspension.user,
                reason="Suspension manually lifted.",
                metadata={"suspension_id": str(suspension.id)},
            )

        send_suspension_lifted_email(
            email=suspension.user.email,
        )

        self.notification_service.create_notification(
            user=suspension.user,
            type="moderation_suspension_lifted",
            title="Suspension Lifted",
            body="Your account suspension has been lifted. Welcome back.",
        )

        self.notification_service.send_push_for_event(
            user=suspension.user,
            event_type="moderation_suspension_lifted",
            title="Suspension Lifted",
            body="Your account suspension has been lifted. Welcome back.",
        )

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_SUSPENSION_LIFTED,
            description=f"Suspension lifted for {suspension.user.email}",
            actor=admin,
            subject=suspension.user,
            metadata={
                "suspension_id": str(suspension.id),
                "original_suspension_reason": suspension.reason,
            },
        )

        return {"detail": "Suspension lifted."}

    # ─────────────────────────────────────────
    # Action Log
    # ─────────────────────────────────────────

    def get_action_log(
        self,
        action_type: str = None,
        skillworld: str = None,
    ):
        return self.repo.get_action_log(
            action_type=action_type,
            skillworld=skillworld,
        )

    # ─────────────────────────────────────────
    # User reporting a comment (learner side)
    # ─────────────────────────────────────────

    def report_comment(
        self,
        comment_id: str,
        reported_by: User,
        category: str,
    ) -> dict:
        comment = self._get_comment_or_raise(comment_id)

        already_reported = CommentReport.objects.filter(
            comment=comment,
            reported_by=reported_by,
        ).exists()

        if already_reported:
            raise ValidationError("You have already reported this comment.")

        with transaction.atomic():
            self.repo.create_report(
                comment=comment,
                reported_by=reported_by,
                category=category,
            )

            report_count = CommentReport.objects.filter(
                comment=comment,
                status=CommentReport.Status.PENDING,
            ).count()

            if report_count >= 1 and not comment.flagged:
                self.repo.flag_comment(comment)

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_COMMENT_REPORTED,
            description=f"Comment {comment_id} reported by {reported_by.email}",
            actor=reported_by,
            subject=comment.user,
            metadata={
                "comment_id": str(comment_id),
                "category": category,
                "report_count": report_count,
            },
        )

        return {"detail": "Comment reported."}

    def suspend_user_directly(
        self,
        user_id: str,
        admin: AdminUser,
        reason: str,
        duration_days: int | None,
    ) -> dict:

        user = self.user_repo.get_by_id(user_id)

        if not user.is_active:
            raise ValidationError("Cannot suspend a deactivated account.")

        if user.status == User.Status.SUSPENDED:
            raise ValidationError("User is already suspended.")

        with transaction.atomic():
            suspension = self.repo.create_suspension(
                user=user,
                suspended_by=admin,
                reason=reason,
                duration_days=duration_days,
            )

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.SUSPENSION,
                performed_by=admin,
                target_user=user,
                reason=reason,
                metadata={
                    "duration_days": duration_days,
                    "expires_at": suspension.expires_at.isoformat()
                    if suspension.expires_at
                    else None,
                    "permanent": suspension.is_permanent,
                    "source": "direct",
                },
            )

        self.notification_service.create_notification(
            user=user,
            type="moderation_suspension",
            title="Account Suspended",
            body=f"Your account has been suspended. Reason: {reason}",
            data={"duration_days": duration_days},
        )

        self.notification_service.send_push_for_event(
            user=user,
            event_type="moderation_suspension",
            title="Account Suspended",
            body=f"Your account has been suspended. Reason: {reason}",
            data={"duration_days": duration_days},
        )

        self.activity_service.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_SUSPENSION,
            description=f"User suspended directly {reason if reason else ''}",
            actor=admin,
            subject=user,
            metadata={
                "reason": reason,
                "duration_days": duration_days,
                "suspension_id": str(suspension.id),
            },
        )

        send_suspension_email(
            email=user.email,
            reason=reason,
            duration_days=duration_days,
        )

        cache.delete(f"auth_user_{user_id}")

        return {
            "detail": "User suspended.",
            "suspension_id": str(suspension.id),
        }

    def handle_ai_flag(
        self,
        comment: EpisodeComment,
        reason: str,
        confidence: float,
        auto_suspend: bool = False,
        duration_days: int | None = 1,
    ) -> None:
        """
        Called by the AI moderation Celery task after a comment
        is classified as harmful.
        """
        with transaction.atomic():
            self.repo.flag_comment(comment)

            self.repo.log_action(
                action_type=ModerationActionLog.ActionType.AI_FLAGGED,
                performed_by=None,
                target_user=comment.user,
                comment=comment,
                reason=reason,
                source=ModerationActionLog.Source.AI,
                metadata={
                    "confidence": confidence,
                    "auto_suspend": auto_suspend,
                },
            )

            if auto_suspend:
                self.repo.create_suspension(
                    user=comment.user,
                    suspended_by=None,
                    reason=f"AI auto-moderation: {reason}",
                    duration_days=duration_days,
                    source=UserSuspension.SuspendedBySource.AI,
                )

                self.notification_service.create_notification(
                    user=comment.user,
                    type="moderation_suspension",
                    title="Account Suspended",
                    body=(
                        "Your account has been temporarily suspended due to a "
                        "community guidelines violation."
                    ),
                    data={"duration_days": duration_days},
                )

    def get_flagged_comments_for_user(self, user_id: str):
        """
        All flagged comments authored by the given user, for moderation review.
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise ValidationError("User not found.")

        return self.repo.get_flagged_comments_for_user(user_id)

    def get_flagged_comment_for_user(
        self, user_id: str, comment_id: str
    ) -> EpisodeComment:
        """
        A single flagged comment authored by the given user.
        """
        comment = self.repo.get_flagged_comment_for_user(user_id, comment_id)
        if not comment:
            raise ValidationError("Flagged comment not found for this user.")

        return comment
