from datetime import timedelta
from django.db.models import Count, ExpressionWrapper, IntegerField, Q
from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError
from skiflux.models import AdminUser, User
from skiflux.models.content import EpisodeComment
from skiflux.models.moderation import (
    CommentReport,
    ModerationActionLog,
    UserSuspension,
)


class ModerationRepository:
    def get_stats(self) -> dict:
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)

        flagged_today = EpisodeComment.objects.filter(
            flagged=True,
            flagged_at__date=today,
        ).count()

        resolved_today = ModerationActionLog.objects.filter(
            action_type__in=[
                ModerationActionLog.ActionType.COMMENT_DELETED,
                ModerationActionLog.ActionType.REPORT_DISMISSED,
            ],
            created_at__date=today,
        ).count()

        active_suspensions = UserSuspension.objects.filter(
            status=UserSuspension.Status.ACTIVE,
        ).count()

        reports_this_week = CommentReport.objects.filter(
            created_at__date__gte=week_start,
        ).count()

        reports_last_week = CommentReport.objects.filter(
            created_at__date__gte=last_week_start,
            created_at__date__lt=week_start,
        ).count()

        if reports_last_week > 0:
            week_change_pct = round(
                ((reports_this_week - reports_last_week) / reports_last_week) * 100, 1
            )
        else:
            week_change_pct = None

        return {
            "flagged_today": flagged_today,
            "resolved_today": resolved_today,
            "active_suspensions": active_suspensions,
            "total_reports_this_week": reports_this_week,
            "reports_vs_last_week_pct": week_change_pct,
        }

    def get_flagged_comments(self, skillworld: str = None):
        qs = (
            EpisodeComment.objects.filter(flagged=True)
            .select_related("user", "episode__season__creator", "episode__season")
            .annotate(
                report_count=Count("reports", distinct=True),
                likes_count=ExpressionWrapper(
                    Count("liked_by", distinct=True)
                    + Count("liked_by_admins", distinct=True),
                    output_field=IntegerField(),
                ),
                top_category=Count("reports__category"),
            )
            .order_by("-report_count", "-created_at")
        )

        if skillworld:
            qs = qs.filter(episode__season__skillworld=skillworld)

        return qs

    def get_flagged_comment_by_id(self, comment_id: str):
        try:
            return (
                EpisodeComment.objects.filter(flagged=True)
                .select_related("user", "episode__season")
                .annotate(
                    report_count=Count("reports", distinct=True),
                )
                .get(id=comment_id)
            )
        except EpisodeComment.DoesNotExist:
            return None

    def get_report_category_for_comment(self, comment_id: str) -> str | None:
        report = (
            CommentReport.objects.filter(comment_id=comment_id)
            .values("category")
            .annotate(count=Count("id"))
            .order_by("-count")
            .first()
        )
        return report["category"] if report else None

    # ─────────────────────────────────────────
    # All Comments
    # ─────────────────────────────────────────

    def get_all_comments(
        self,
        search: str = None,
        filter_type: str = None,
        skillworld: str = None,
    ):
        qs = (
            EpisodeComment.objects.all()
            .select_related("user", "episode__season")
            .annotate(
                report_count=Count("reports", distinct=True),
                likes_count=ExpressionWrapper(
                    Count("liked_by", distinct=True)
                    + Count("liked_by_admins", distinct=True),
                    output_field=IntegerField(),
                ),
            )
            .order_by("-created_at")
        )

        if search:
            qs = qs.filter(
                Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__username__icontains=search)
                | Q(text__icontains=search)
            )

        if filter_type == "flagged":
            qs = qs.filter(flagged=True)
        elif filter_type == "deleted":
            qs = qs.filter(
                id__in=ModerationActionLog.objects.filter(
                    action_type=ModerationActionLog.ActionType.COMMENT_DELETED,
                ).values_list("comment_id", flat=True)
            )

        if skillworld:
            qs = qs.filter(episode__season__skillworld=skillworld)

        return qs

    def get_comment_by_id(self, comment_id: str):
        try:
            return EpisodeComment.objects.select_related("user", "episode__season").get(
                id=comment_id
            )
        except EpisodeComment.DoesNotExist:
            return None

    def delete_comment(self, comment: EpisodeComment) -> None:
        comment.delete()

    def flag_comment(self, comment: EpisodeComment) -> None:
        comment.flagged = True
        comment.flagged_at = timezone.now()
        comment.save(update_fields=["flagged", "flagged_at"])

    def unflag_comment(self, comment: EpisodeComment) -> None:
        comment.flagged = False
        comment.save(update_fields=["flagged"])

    # ─────────────────────────────────────────
    # Reports
    # ─────────────────────────────────────────

    def create_report(
        self,
        comment: EpisodeComment,
        reported_by: User,
        category: str,
    ) -> CommentReport:
        report, _ = CommentReport.objects.get_or_create(
            comment=comment,
            reported_by=reported_by,
            defaults={"category": category},
        )
        return report

    def resolve_reports_for_comment(self, comment_id: str) -> None:
        CommentReport.objects.filter(
            comment_id=comment_id,
            status=CommentReport.Status.PENDING,
        ).update(status=CommentReport.Status.RESOLVED)

    def dismiss_reports_for_comment(self, comment_id: str) -> None:
        CommentReport.objects.filter(
            comment_id=comment_id,
            status=CommentReport.Status.PENDING,
        ).update(status=CommentReport.Status.DISMISSED)

    # ─────────────────────────────────────────
    # Suspensions
    # ─────────────────────────────────────────

    def get_active_suspensions(self, skillworld: str = None):
        qs = (
            UserSuspension.objects.filter(status=UserSuspension.Status.ACTIVE)
            .select_related("user", "suspended_by")
            .order_by("-created_at")
        )

        if skillworld:
            from django.db import connection

            if connection.vendor == "postgresql":
                qs = qs.filter(user__skillworld__contains=skillworld)
            else:
                qs = qs.filter(user__skillworld__icontains=f'"{skillworld}"')

        return qs

    def get_suspension_by_id(self, suspension_id: str):
        try:
            return UserSuspension.objects.select_related("user", "suspended_by").get(
                id=suspension_id
            )
        except UserSuspension.DoesNotExist:
            return None

    def create_suspension(
        self,
        user: User,
        suspended_by: AdminUser | None,
        reason: str,
        duration_days: int | None,  # None = permanent
        source: str = UserSuspension.SuspendedBySource.ADMIN,
    ) -> UserSuspension:
        expires_at = (
            timezone.now() + timedelta(days=duration_days)
            if duration_days is not None
            else None
        )

        existing = UserSuspension.objects.filter(
            user=user,
            status=UserSuspension.Status.ACTIVE,
        ).exists()

        if existing:
            raise ValidationError("User already has an active suspension.")

        suspension = UserSuspension.objects.create(
            user=user,
            suspended_by=suspended_by,
            reason=reason,
            duration_days=duration_days,
            expires_at=expires_at,
            source=source,
        )

        user.status = User.Status.SUSPENDED
        user.save(update_fields=["status"])

        return suspension

    def lift_suspension(
        self,
        suspension: UserSuspension,
        lifted_by: AdminUser,
    ) -> UserSuspension:
        suspension.status = UserSuspension.Status.LIFTED
        suspension.lifted_by = lifted_by
        suspension.lifted_at = timezone.now()
        suspension.save(update_fields=["status", "lifted_by", "lifted_at"])

        # restore user status only if no other active suspensions
        has_other = (
            UserSuspension.objects.filter(
                user=suspension.user,
                status=UserSuspension.Status.ACTIVE,
            )
            .exclude(id=suspension.id)
            .exists()
        )

        if not has_other:
            suspension.user.status = User.Status.ACTIVE
            suspension.user.save(update_fields=["status"])

        return suspension

    def expire_due_suspensions(self) -> int:
        """Called by a periodic Celery beat task."""
        now = timezone.now()
        with transaction.atomic():
            expired = UserSuspension.objects.filter(
                status=UserSuspension.Status.ACTIVE,
                expires_at__lte=now,
            )
            count = expired.count()
            user_ids = list(expired.values_list("user_id", flat=True))
            expired.update(status=UserSuspension.Status.EXPIRED)

            # restore user status for those with no remaining active suspensions
            for user_id in user_ids:
                still_suspended = UserSuspension.objects.filter(
                    user_id=user_id,
                    status=UserSuspension.Status.ACTIVE,
                ).exists()
                if not still_suspended:
                    User.objects.filter(id=user_id).update(status=User.Status.ACTIVE)

            return count

    # ─────────────────────────────────────────
    # Action Log
    # ─────────────────────────────────────────

    def log_action(
        self,
        action_type: str,
        target_user: User,
        performed_by: AdminUser | None = None,
        comment: EpisodeComment | None = None,
        reason: str = "",
        metadata: dict = None,
        source: str = ModerationActionLog.Source.ADMIN,
    ) -> ModerationActionLog:
        return ModerationActionLog.objects.create(
            action_type=action_type,
            performed_by=performed_by,
            target_user=target_user,
            comment=comment,
            reason=reason,
            metadata=metadata or {},
            source=source,
        )

    def get_action_log(self, action_type: str = None, skillworld: str = None):
        qs = (
            ModerationActionLog.objects.all()
            .select_related(
                "performed_by",
                "target_user",
                "comment__episode__season",
            )
            .order_by("-created_at")
        )

        if action_type:
            qs = qs.filter(action_type=action_type)

        if skillworld:
            qs = qs.filter(comment__episode__season__skillworld=skillworld)

        return qs

    def get_flagged_comments_for_user(self, user_id: str):
        """
        Returns all flagged comments authored by a given user, annotated
        with report counts and like counts, with related objects prefetched
        for serialization (user, episode/season, reports + reporters, likes).
        """
        return (
            EpisodeComment.objects.filter(
                user_id=user_id,
                flagged=True,
            )
            .select_related(
                "user",
                "episode",
                "episode__season",
                "episode__season__creator",
            )
            .prefetch_related(
                "reports",
                "reports__reported_by",
                "liked_by",
                "liked_by_admins",
            )
            .annotate(
                report_count=Count("reports", distinct=True),
                pending_report_count=Count(
                    "reports",
                    filter=Q(reports__status=CommentReport.Status.PENDING),
                    distinct=True,
                ),
                likes_count=ExpressionWrapper(
                    Count("liked_by", distinct=True)
                    + Count("liked_by_admins", distinct=True),
                    output_field=IntegerField(),
                ),
            )
            .order_by("-report_count", "-created_at")
        )

    def get_flagged_comment_for_user(self, user_id: str, comment_id: str):
        """
        Single flagged comment belonging to a specific user, with the
        same annotations/prefetches as get_flagged_comments_for_user.
        """
        try:
            return (
                EpisodeComment.objects.filter(
                    user_id=user_id,
                    id=comment_id,
                    flagged=True,
                )
                .select_related(
                    "user",
                    "episode",
                    "episode__season",
                    "episode__season__creator",
                )
                .prefetch_related(
                    "reports",
                    "reports__reported_by",
                    "liked_by",
                    "liked_by_admins",
                )
                .annotate(
                    report_count=Count("reports", distinct=True),
                    pending_report_count=Count(
                        "reports",
                        filter=Q(reports__status=CommentReport.Status.PENDING),
                        distinct=True,
                    ),
                    likes_count=ExpressionWrapper(
                        Count("liked_by", distinct=True)
                        + Count("liked_by_admins", distinct=True),
                        output_field=IntegerField(),
                    ),
                )
                .get()
            )
        except EpisodeComment.DoesNotExist:
            return None
