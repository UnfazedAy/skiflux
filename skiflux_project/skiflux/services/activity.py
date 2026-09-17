"""
Service layer for activity logging business logic.
Provides clean interface for logging activities throughout the application.
"""

from skiflux.repositories.activity import ActivityRepository
from skiflux.repositories.user_repository import UserRepository
from skiflux.models.activity import ActivityLog
from rest_framework.exceptions import ValidationError


class ActivityService:
    """
    Service for managing activity logs.
    Provides high-level methods to log activities and retrieve them.
    """

    @staticmethod
    def log_activity(
        action_type: str,
        description: str,
        actor=None,
        subject=None,
        metadata: dict = None,
    ) -> ActivityLog:
        """
        Log an activity to the system.

        Args:
            action_type: Type of action (use ActivityLog.ActionType)
            description: Human-readable description
            actor: User who performed action (admin/system)
            subject: User affected by action
            metadata: Additional context

        Returns:
            Created ActivityLog instance

        Example:
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.USER_VERIFIED,
                description="User email verified",
                subject=user_instance,
                actor=admin_instance
            )
        """
        return ActivityRepository.create_activity(
            action_type=action_type,
            description=description,
            actor=actor,
            subject=subject,
            metadata=metadata or {},
        )

    @staticmethod
    def get_dashboard_activities(limit: int = 20):
        """Get recent activities for dashboard display"""
        return ActivityRepository.get_recent_activities(limit=limit)

    @staticmethod
    def get_activity_stats():
        """
        Get summary statistics about recent activities.
        Useful for dashboard analytics.
        """
        recent_activities = ActivityRepository.get_recent_activities(limit=100)

        stats = {
            "total_activities": len(recent_activities),
            "by_type": {},
            "by_actor": {},
        }

        for activity in recent_activities:
            # Count by type
            action_type = activity.get_action_type_display()
            stats["by_type"][action_type] = stats["by_type"].get(action_type, 0) + 1

            # Count by actor
            actor = activity.actor_admin or activity.actor_user
            if actor:
                actor_name = (
                    f"{actor.first_name} {actor.last_name}".strip() or actor.email
                )
                stats["by_actor"][actor_name] = stats["by_actor"].get(actor_name, 0) + 1

        return stats

    @staticmethod
    def get_user_activity_feed(user_id, limit: int = None):
        user = UserRepository().get_by_id(user_id)
        if not user:
            raise ValidationError("User not found.")
        return ActivityRepository.get_user_activities(user, limit=limit)

    @staticmethod
    def get_activities_by_date_range(start_date, end_date, action_type=None):
        """Get activities within a date range"""
        return ActivityRepository.get_activities_in_time_range(
            start_date, end_date, action_type=action_type
        )
