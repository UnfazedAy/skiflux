"""
Repository for ActivityLog database operations.
Handles all database queries related to activity logs.
"""

from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from skiflux.models import AdminUser, User
from skiflux.models.activity import ActivityLog


class ActivityRepository:
    """Repository for Activity database operations"""

    @staticmethod
    def create_activity(
        action_type: str,
        description: str,
        actor=None,
        subject=None,
        metadata: dict = None,
    ) -> ActivityLog:
        """
        Create a new activity log entry.

        Args:
            action_type: Type of action (from ActionType choices)
            description: Human-readable description
            actor: User who performed the action (optional)
            subject: User who is subject of the action (optional)
            metadata: Additional context (optional)

        Returns:
            Created ActivityLog instance
        """
        if metadata is None:
            metadata = {}

        actor_fields = ActivityRepository._actor_fields(actor, "actor")
        subject_fields = ActivityRepository._actor_fields(subject, "subject")

        return ActivityLog.objects.create(
            action_type=action_type,
            description=description,
            metadata=metadata,
            **actor_fields,
            **subject_fields,
        )

    @staticmethod
    def _actor_fields(value, prefix: str) -> dict:
        if isinstance(value, AdminUser):
            return {f"{prefix}_admin": value}
        if isinstance(value, User):
            return {f"{prefix}_user": value}
        return {}

    @staticmethod
    def get_recent_activities(limit: int = 20) -> QuerySet:
        """
        Get recent activities for the dashboard.

        Args:
            limit: Maximum number of activities to return

        Returns:
            QuerySet of recent ActivityLog entries
        """
        return ActivityLog.objects.select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )[:limit]

    @staticmethod
    def get_activities_by_type(action_type: str, limit: int = 20) -> QuerySet:
        """Get activities filtered by action type"""
        return ActivityLog.objects.filter(action_type=action_type).select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )[:limit]

    @staticmethod
    def get_user_activities(user, limit: int = None) -> QuerySet:
        """Get activities where the user is either the subject or the actor."""
        qs = (
            ActivityLog.objects.filter(Q(subject_user=user) | Q(actor_user=user))
            .select_related(
                "actor_user", "actor_admin", "subject_user", "subject_admin"
            )
            .order_by("-timestamp")
        )
        if limit:
            qs = qs[:limit]
        return qs

    @staticmethod
    def get_activities_by_actor(actor, limit: int = 20) -> QuerySet:
        """Get activities initiated by a specific user/admin"""
        fields = ActivityRepository._actor_fields(actor, "actor")
        return ActivityLog.objects.filter(**fields).select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )[:limit]

    @staticmethod
    def get_activities_in_time_range(
        start_time, end_time, action_type: str = None
    ) -> QuerySet:
        """
        Get activities within a specific time range.

        Args:
            start_time: Start datetime
            end_time: End datetime
            action_type: Optional filter by action type
        """
        query = ActivityLog.objects.filter(
            timestamp__gte=start_time, timestamp__lte=end_time
        )

        if action_type:
            query = query.filter(action_type=action_type)

        return query.select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )

    @staticmethod
    def get_activities_today() -> QuerySet:
        """Get all activities from today"""
        today = timezone.localdate()
        return ActivityLog.objects.filter(timestamp__date=today).select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )

    @staticmethod
    def get_activities_this_week() -> QuerySet:
        """Get all activities from this week"""
        week_ago = timezone.now() - timedelta(days=7)
        return ActivityLog.objects.filter(timestamp__gte=week_ago).select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )

    @staticmethod
    def search_activities(search_query: str, limit: int = 20) -> QuerySet:
        """
        Search activities by description or action type.

        Args:
            search_query: Search term
            limit: Maximum results
        """
        return ActivityLog.objects.filter(
            Q(description__icontains=search_query)
            | Q(action_type__icontains=search_query)
        ).select_related(
            "actor_user",
            "actor_admin",
            "subject_user",
            "subject_admin",
        )[:limit]
